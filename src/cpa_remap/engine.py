import math
import datetime
import os
import re
import subprocess
import json
import shutil
from pathlib import Path

from .models import Cone, Wire, Node, Module

try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(iterable, **_kwargs):
        return iterable

class ABC:
    def __init__(self, libs, executable='abc'):
        if os.path.exists('abc.history'):
            os.remove('abc.history')
        self.process = subprocess.Popen(
            [executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            text=True
        )
        self.mark = 'cmd_over' # 标记命令执行结束的字符串
        count = 0
        for lib in libs:
            log(f'abc read_lib {lib}')
            count += 1
            if count == 1:
                self.execute_command(f'read_lib {lib};')
            else:
                self.execute_command(f'read_lib -m {lib};')

    def execute_command(self, cmd):
        # 发送命令并刷新输入缓冲区
        self.process.stdin.write(f'{cmd} echo "{self.mark}";\n')
        self.process.stdin.flush()
        # 读取输出
        output = []
        flag = 0
        while True:
            line = self.process.stdout.readline()
            if not line:
                break  # 进程结束
            output.append(line)
            if self.mark in line:
                flag += 1
                if flag == 2:
                    break
        return ''.join(output)

    def empty(self): # 清空ABC工作区
        self.execute_command('empty;')
    
    def kill(self): # 终止进程
        self.process.stdin.close()
        self.process.terminate()
        self.process.wait()

class STA:
    def __init__(self, libs, executable='sta'):
        self.process = subprocess.Popen(
            [executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            text=True
        )
        for lib in libs:
            log(f'opensta read_liberty {lib}')
            self.execute_command(f'read_liberty {lib}')

    def execute_command(self, cmd):
        # 发送命令并刷新输入缓冲区
        self.process.stdin.write(f'{cmd}; help help\n')
        self.process.stdin.flush()
        # 读取输出
        while True:
            line = self.process.stdout.readline()
            if not line:
                break  # 进程结束
            if 'help [pattern]' in line:
                break  # 命令执行完毕

    def kill(self): # 终止进程
        self.process.stdin.close()
        self.process.terminate()
        self.process.wait()

def log(info):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] : {info}")

def proc_cell_name(cell_name):
    cell_name = cell_name.rsplit("_", 1)[0]
    return cell_name

def get_distance(nodeObj_1: Node, nodeObj_2: Node) -> float:
    """计算两个节点之间的曼哈顿距离"""
    if nodeObj_1.location == None:
        assert False, f'node {nodeObj_1.inst} location is None'
    if nodeObj_2.location == None:
        assert False, f'node {nodeObj_2.inst} location is None'
    return abs(nodeObj_1.location[0] - nodeObj_2.location[0]) + abs(nodeObj_1.location[1] - nodeObj_2.location[1])

def merge_dict(d:dict) -> dict:
    """将字典中值存在交集的键合并，返回合并后的字典"""
    parent = {k: k for k in d}
    elem_map = {}
    def find(k):
        if parent[k] != k:
            parent[k] = find(parent[k])
        return parent[k]
    # 合并存在交集的键
    for key, values in d.items():
        for v in values:
            if v in elem_map:
                r1, r2 = find(key), find(elem_map[v])
                if r1 != r2:
                    parent[r2] = r1
            else:
                elem_map[v] = key
    # 收集每个根节点对应的所有元素
    merged = {}
    for k in d:
        root = find(k)
        if root not in merged:
            merged[root] = set(d[k])
        else:
            merged[root].update(d[k])
    # 仅保留根节点作为键，并转为列表
    return {k: list(v) for k, v in merged.items()}

def merge_key_path(paths:list, inst_to_nodeObj:dict) -> dict:
    """将同一批次多条关键路径的重复节点进行合并，返回合并后的子图集合"""
    # 第一步：排除每条路径中被前面批次处理过的节点，在这种情况下，一条路径可能会被分成多个子图
    # temp_dit存储了所有子图
    temp_dit = {}
    temp_id = 0
    for pathObj in paths:
        path = pathObj.nodes[1:-1] # 去除关键路径首尾的时序节点
        flag = True
        for node in path:
            if node not in inst_to_nodeObj:
                continue
            nodeObj = inst_to_nodeObj[node]
            if nodeObj.cone_id != None: # 该节点在前面的批次中已经被处理过
                if flag:
                    flag = False
                    temp_id += 1
                continue
            else:
                flag = True
                if temp_id not in temp_dit:
                    temp_dit[temp_id] = []
                temp_dit[temp_id].append(node)
        temp_id += 1
    # 第二步：将temp_dit中的子图进行合并，存在公共节点的子图需要被合并成一个
    return merge_dict(temp_dit)

def cut_merged_key_path(distence_threshold:int, coneId_to_coneObj:dict, coneId:int, sigle_path_sub_graph:list, inst_to_nodeObj:dict) -> tuple[dict, int]:
    """将合并后的单个子图进行切割，返回切割后的初始逻辑锥集合"""
    # 初始化分组
    for node_1 in sigle_path_sub_graph:
        nodeObj_1 = inst_to_nodeObj[node_1]
        if nodeObj_1.cone_id != None or 'BUF' in nodeObj_1.full_cell or 'INV' in nodeObj_1.full_cell: # 该节点在本批次中已经被处理过或者该节点是BUF、INV
            continue
        if len(nodeObj_1.output_wires) > 1: # 跳过多输出节点
            continue
        new_cone = Cone(coneId)
        new_cone.module = nodeObj_1.module
        nodeObj_1.cone_id = coneId
        new_cone.add_node(node_1)
        new_cone.update_wires(inst_to_nodeObj)
        all_connected_nodes, cone_nodes = new_cone.get_all_connected_nodes()
        while all_connected_nodes:
            node_2 = all_connected_nodes.pop()
            nodeObj_2 = inst_to_nodeObj[node_2]
            cone_node = cone_nodes.pop()
            cone_nodeObj = inst_to_nodeObj[cone_node]
            if len(nodeObj_2.output_wires) > 1: # 跳过多输出节点
                continue
            # 该节点不在当前处理的子图中或者该节点是BUF
            if node_2 not in sigle_path_sub_graph or 'BUF' in nodeObj_2.full_cell:
                continue
            # 如果使用两个inv远距离传递信号
            if 'INV' in nodeObj_2.full_cell:
                # 处理输入情况，如果上游是INV或者BUF，那么跳过这个INV
                input_wire = nodeObj_2.input_wires[0]
                if len(nodeObj_2.input_wires) > 1:
                    assert False
                if input_wire[0] is not None:
                    upstream_node = input_wire[0].split(':')[0]
                    upstream_nodeObj = inst_to_nodeObj[upstream_node]
                    if 'INV' in upstream_nodeObj.full_cell or 'BUF' in upstream_nodeObj.full_cell:
                        continue
                # 处理输出情况，如果下游在当前子图中并且不是INV或者BUF，那么应该纳入这个INV
                skip_flag = True
                for output_wire in nodeObj_2.output_wires:
                    if output_wire[1] is not None:
                        downstream_node = output_wire[1].split(':')[0]
                        downstream_nodeObj = inst_to_nodeObj[downstream_node]
                        if downstream_node not in sigle_path_sub_graph or 'INV' in downstream_nodeObj.full_cell or 'BUF' in downstream_nodeObj.full_cell:
                            continue
                        skip_flag = False
                        break
                if skip_flag:
                    continue
            if get_distance(cone_nodeObj, nodeObj_2) <= distence_threshold:
                if nodeObj_2.cone_id != None or nodeObj_2.module != new_cone.module:
                    assert False
                nodeObj_2.cone_id = coneId
                new_cone.add_node(node_2)
                new_cone.update_wires(inst_to_nodeObj)
                all_connected_nodes, cone_nodes = new_cone.get_all_connected_nodes()

        new_cone.update_root_nodes(inst_to_nodeObj)
        coneId_to_coneObj[coneId] = new_cone
        coneId += 1
    
    return coneId_to_coneObj, coneId

def get_cone(distence_threshold:int, coneObj:Cone, inst_to_nodeObj:dict[Node], cell_to_cellObj:dict) -> Cone:
    """对每一个初始逻辑锥进行完整逻辑锥构造，只构造没有额外输出的逻辑锥"""
    connected_nodes, cone_nodes = coneObj.get_connected_nodes()
    while connected_nodes:
        node = connected_nodes.pop()
        nodeObj = inst_to_nodeObj[node]
        cone_node = cone_nodes.pop()
        cone_nodeObj = inst_to_nodeObj[cone_node]
        if nodeObj.cone_id != None or 'BUF' in nodeObj.full_cell: # 该节点被其他逻辑锥占用或者该节点是BUF
            continue
        elif 'INV' in nodeObj.full_cell: # 如果使用两个inv或者涉及到BUF远距离传递信号
            input_wire = nodeObj.input_wires[0]
            if input_wire[0] is not None:
                upstream_node = input_wire[0].split(':')[0]
                upstream_nodeObj = inst_to_nodeObj[upstream_node]
                if 'INV' in upstream_nodeObj.full_cell or 'BUF' in upstream_nodeObj.full_cell:
                    continue
        elif not cell_to_cellObj[nodeObj.cell].is_comb: # 该节点不是组合单元
            continue
        elif get_distance(nodeObj, cone_nodeObj) > distence_threshold: # 该节点距离逻辑锥对应节点过远
            continue
        elif len(nodeObj.output_wires) > 1: # 该节点有多个输出
            flag = False
            for wire in nodeObj.output_wires:
                if wire[1] is None:
                    flag = True
                    break
                elif wire[1].split(':')[0] not in coneObj.nodes:
                    flag = True
                    break
            if flag:
                continue
            else:
                nodeObj.cone_id = coneObj.id
                coneObj.add_node(node)
                for wire in nodeObj.input_wires:
                    if wire[0] != None and wire[0].split(':')[0] not in coneObj.nodes:
                        connected_nodes.append(wire[0].split(':')[0])
                        cone_nodes.append(node)
        else:
            nodeObj.cone_id = coneObj.id
            coneObj.add_node(node)
            for wire in nodeObj.input_wires:
                if wire[0] != None and wire[0].split(':')[0] not in coneObj.nodes:
                    connected_nodes.append(wire[0].split(':')[0])
                    cone_nodes.append(node)

    return coneObj

def remap(design:str, coneObj:Cone, inst_to_nodeObj:dict, abc_tool:ABC, sta_tool:STA, new_gates:dict, en_count:bool, cell_to_cellObj:dict, relax:int, output_dir:str | os.PathLike='remap_results') -> tuple[int, dict, Cone, bool]:
    """对一个完整逻辑锥进行重映射"""
    run_path = (Path(output_dir) / design).as_posix()
    # 提取逻辑锥输入、输出、节点连接关系
    out_port_to_size = {}
    wireName_to_wireObj = {}
    wireId = 0
    for node in coneObj.nodes:
        nodeObj = inst_to_nodeObj[node]
        for wire in nodeObj.input_wires:
            if wire[2] not in wireName_to_wireObj:
                wireName_to_wireObj[wire[2]] = Wire(wire[2])
                wireName_to_wireObj[wire[2]].new_name = f'net_hmx_{wireId}'
                wireId += 1
            wireName_to_wireObj[wire[2]].add_port(wire[1], 'input')
            if wire[0] == None or wire[0].split(':')[0] not in coneObj.nodes:
                wireName_to_wireObj[wire[2]].input_wire = True
        for wire in nodeObj.output_wires:
            if wire[2] not in wireName_to_wireObj:
                wireName_to_wireObj[wire[2]] = Wire(wire[2])
                wireName_to_wireObj[wire[2]].new_name = f'net_hmx_{wireId}'
                wireId += 1
            wireName_to_wireObj[wire[2]].add_port(wire[0], 'output')
            if wire[1] == None or wire[1].split(':')[0] not in coneObj.nodes:
                wireName_to_wireObj[wire[2]].output_wire = True
                this_node = wire[0].split(':')[0]
                this_nodeObj = inst_to_nodeObj[this_node]
                this_size = this_nodeObj.full_cell.rsplit("_", 1)[1]
                out_port_to_size[wireName_to_wireObj[wire[2]].new_name] = this_size
    inputs = set()
    outputs = set()
    wires = set()
    node_port_to_wire_new_name = {} # 锥内节点端口到新线名的映射
    for wireObj in wireName_to_wireObj.values():
        if wireObj.input_wire and wireObj.output_wire:
            assert False
        if wireObj.input_wire:
            inputs.add(wireObj.new_name)
            coneObj.port_map[wireObj.new_name] = wireObj.name
        elif wireObj.output_wire:
            outputs.add(wireObj.new_name)
            coneObj.port_map[wireObj.new_name] = wireObj.name
        else:
            wires.add(wireObj.new_name)

        if wireObj.from_pre:
            node_port_to_wire_new_name[wireObj.from_pre] = wireObj.new_name
        for port in wireObj.to_nxt:
            node_port_to_wire_new_name[port] = wireObj.new_name
    # 写入临时网表文件
    with open(f'{run_path}/cone_hmx_{coneObj.id}.v', 'w') as f:
        f.write(f'module cone_hmx_{coneObj.id} (\n')
        ports = inputs | outputs
        lenth = len(ports)
        for port in ports:
            if lenth == 1:
                f.write(f'\t{port});\n')
            else:
                f.write(f'\t{port},\n')
                lenth -= 1
        for i in inputs:
            f.write(f'\tinput {i};\n')
        for i in outputs:
            f.write(f'\toutput {i};\n')
        for i in wires:
            f.write(f'\twire {i};\n')
        f.write(f'\twire temp;\n')
        f.write('\n')
        for node in coneObj.nodes:
            nodeObj = inst_to_nodeObj[node]
            f.write(f'\t{nodeObj.full_cell} {nodeObj.inst} (\n')
            for p in nodeObj.disconnect:
                f.write(f'\t\t.{p}(temp),\n')
            ports = set()
            for wire in nodeObj.input_wires:
                ports.add(wire[1])
            for wire in nodeObj.output_wires:
                ports.add(wire[0])
            lenth = len(ports)
            cellObj = cell_to_cellObj[nodeObj.cell]
            if lenth + len(nodeObj.disconnect) != len(cellObj.inputs) + len(cellObj.outputs):
                assert False
            for port in ports:
                portName = port.split(':')[1]
                if lenth == 1:
                    f.write(f'\t\t.{portName}({node_port_to_wire_new_name[port]}));\n')
                else:
                    f.write(f'\t\t.{portName}({node_port_to_wire_new_name[port]}),\n')
                    lenth -= 1
        f.write('endmodule\n\n')
    # 如果这个逻辑锥少于一个单元，不进行后续优化
    if len(coneObj.nodes) <= 1:
        coneObj.release_nodes(inst_to_nodeObj)
        return None, None, new_gates, coneObj, False
    # 调用opensta工具提取时序报告
    sta_tool.execute_command(f'read_verilog {run_path}/cone_hmx_{coneObj.id}.v')
    sta_tool.execute_command(f'link_design cone_hmx_{coneObj.id}')
    flag = True
    for o in outputs:
        for i in inputs:
            if flag:
                sta_tool.execute_command(f'report_checks -unconstrained -from {i} -to {o} -digits 4 > {run_path}/cone_hmx_{coneObj.id}.rpt')
                flag = False
            else:
                sta_tool.execute_command(f'report_checks -unconstrained -from {i} -to {o} -digits 4 >> {run_path}/cone_hmx_{coneObj.id}.rpt')
    # 根据时序报告生成约束脚本
    with open(f'{run_path}/cone_hmx_{coneObj.id}.rpt', 'r') as f:
        lines = f.readlines()
    path_delay = {}
    max_delay = 0
    for line in lines:
        line = line.strip()
        if line.startswith('Startpoint'):
            start_point = re.search(r'Startpoint:\s+(\w+)\s*\(', line).group(1)
            continue
        result = re.search(r'(\d+\.?\d*)\s+data arrival time', line)
        if result:
            if float(result.group(1)) > max_delay:
                max_delay = float(result.group(1))
            path_delay[start_point] = float(result.group(1))
    with open(f'{run_path}/cone_hmx_{coneObj.id}_constra', 'w') as f:
        for start_point in path_delay:
            f.write(f'.SCL_INPUT_ARR {start_point} {1000 * (max_delay - path_delay[start_point])}\n')
    # 调用ABC工具执行约束下的逻辑映射
    abc_command = f'read -m {run_path}/cone_hmx_{coneObj.id}.v;topo;stime;read_constr -n {run_path}/cone_hmx_{coneObj.id}_constra;strash;map;write_verilog {run_path}/cone_hmx_{coneObj.id}_maped.v;'
#    abc_command = f'read -m {run_path}/cone_hmx_{coneObj.id}.v;topo;stime;strash;&get -n;&fraig -x;&put;scorr;dc2;dretime;strash;&get -n;&dch -f;&nf -D 1;&put;buffer;upsize -D 1;dnsize -D 1;write_verilog {run_path}/cone_hmx_{coneObj.id}_maped.v;'
#    abc_command = f'read -m {run_path}/cone_hmx_{coneObj.id}.v;topo;stime;strash;dretime;map -s -D 1;buffer;upsize -D 1;dnsize -D 1;write_verilog {run_path}/cone_hmx_{coneObj.id}_maped.v;'
    output = abc_tool.execute_command(abc_command)
    if 'undefined object types interpreted as blackboxes' in output:
        coneObj.release_nodes(inst_to_nodeObj)
        return None, None, new_gates, coneObj, False
    # 读取优化前逻辑锥信息
    result = re.findall(r'Gates\s*=\s*(\d+).+?Cap\s*=\s*([\d.]+)\s+ff.+?Area\s*=\s*([\d.]+).+?Delay\s*=\s*([\d.]+)\s+ps', output)
    pre_gates = result[0][0]
    pre_cap = result[0][1]
    pre_area = result[0][2]
    pre_delay = result[0][3]
    # 修改输出端口对应单元size，与原网表保持一致
    with open(f'{run_path}/cone_hmx_{coneObj.id}_maped.v', 'r') as f:
        data = f.read()
        head_info = re.search(r'(module\s+[^;]+?;\s+input\s+[^;]+?;\s+output\s+[^;]+?;(?:\s+wire\s+[^;]+?;)*)', data, re.DOTALL).group(1)
        wire_to_wireObj = {}
        inst_to_instInfo = {}
        inst_list = re.findall(r'(\w+\s+\S+\s*\(\.[^;]+;)', data, re.DOTALL)
        for inst in inst_list:
            result = re.search(r'(\w+)\s+(\S+)\s*\(\.', inst)
            first_name = result.group(1) # 实例单元名
            inst_name = result.group(2) # 实例名
            cell_name = proc_cell_name(first_name) # 处理后标准单元格式
            inst_to_instInfo[inst_name] = [cell_name, first_name, inst]
            # 记录实例之间的连接关系，每一层用一个字典记录线与节点的关系
            wire_list = re.findall(r'\.(\w+)\(([^)]*)\)', inst, re.DOTALL)
            for (port_name, wire_name) in wire_list:
                full_port_name = f'{inst_name}:{port_name}'
                if port_name in cell_to_cellObj[cell_name].inputs:
                    port_direction = 'input'
                elif port_name in cell_to_cellObj[cell_name].outputs:
                    port_direction = 'output'
                else:
                    assert False, 'can not find port name'
                if wire_name == '': # 端口悬空的情况
                    assert False
                if wire_name not in wire_to_wireObj:
                    wire_to_wireObj[wire_name] = Wire(wire_name)
                wire_to_wireObj[wire_name].add_port(full_port_name, port_direction)
        for wireObj in wire_to_wireObj.values():
            if wireObj.name in out_port_to_size:
                size = out_port_to_size[wireObj.name]
                this_node = wireObj.from_pre.split(':')[0]
                cellObj = cell_to_cellObj[inst_to_instInfo[this_node][0]]
                if size in cellObj.version_to_cell:
                    new_cell = cellObj.version_to_cell[size]
                    inst_info = inst_to_instInfo[this_node][2]
                    inst_to_instInfo[this_node][2] = inst_info.replace(inst_to_instInfo[this_node][1], new_cell)
        new_data = head_info + '\n' + '\n'.join([inst_to_instInfo[inst][2] for inst in inst_to_instInfo.keys()]) + '\nendmodule\n'
    with open(f'{run_path}/cone_hmx_{coneObj.id}_size_opt.v', 'w') as f:
        f.write(new_data)
    coneObj.info = new_data
    coneObj.update_new_gates()
    # 调用opensta工具提取时序报告
    sta_tool.execute_command(f'read_verilog {run_path}/cone_hmx_{coneObj.id}_size_opt.v')
    sta_tool.execute_command(f'link_design cone_hmx_{coneObj.id}')
    flag = True
    for o in outputs:
        for i in inputs:
            if flag:
                sta_tool.execute_command(f'report_checks -unconstrained -from {i} -to {o} -digits 4 > {run_path}/cone_hmx_{coneObj.id}_size_opt.rpt')
                flag = False
            else:
                sta_tool.execute_command(f'report_checks -unconstrained -from {i} -to {o} -digits 4 >> {run_path}/cone_hmx_{coneObj.id}_size_opt.rpt')
    # 生成优化前后时序对比报告
    with open(f'{run_path}/cone_hmx_{coneObj.id}.rpt', 'r') as f:
        lines = f.readlines()
    path_delay = {}
    for line in lines:
        line = line.strip()
        if line.startswith('Startpoint'):
            start_point = re.search(r'Startpoint:\s+(\w+)\s*\(', line).group(1)
            continue
        if line.startswith('Endpoint'):
            end_point = re.search(r'Endpoint:\s+(\w+)\s*\(', line).group(1)
            continue
        result = re.search(r'(\d+\.?\d*)\s+data arrival time', line)
        if result:
            pair = start_point + '->' + end_point
            path_delay[pair] = [float(result.group(1))]
    with open(f'{run_path}/cone_hmx_{coneObj.id}_size_opt.rpt', 'r') as f:
        lines = f.readlines()
    for line in lines:
        line = line.strip()
        if line.startswith('Startpoint'):
            start_point = re.search(r'Startpoint:\s+(\w+)\s*\(', line).group(1)
            continue
        if line.startswith('Endpoint'):
            end_point = re.search(r'Endpoint:\s+(\w+)\s*\(', line).group(1)
            continue
        result = re.search(r'(\d+\.?\d*)\s+data arrival time', line)
        if result:
            pair = start_point + '->' + end_point
            path_delay[pair].append(float(result.group(1)))
    max_relax = 0
    for pair, delays in path_delay.items():
        diff = delays[0] - delays[1]
        if diff < 0 and abs(diff)*100/delays[0] > max_relax: # 全路径最大恶化松弛计算
            max_relax = abs(diff)*100/delays[0]
        path_delay[pair].append(round(diff, 4))
    path_delay = {k: v for k, v in sorted(path_delay.items(), key=lambda item: item[1][2])}
    with open(f'{run_path}/cone_hmx_{coneObj.id}_compara.txt', 'w') as f:
        header = "{:<40} | {:<20} | {:<20} | {:<20}"
        divider = "-----------------------------------------|----------------------|----------------------|----------------------"
        row = "{:<40} | {:>20} | {:>20} | {:>20}"
        f.write(header.format("start-end", "Original", "Optimized", "Difference") + "\n")
        f.write(divider + "\n")
        for pair, delays in path_delay.items():
            f.write(row.format(f"{pair}", f"{delays[0]}", f"{delays[1]}", f"{delays[2]}") + "\n")
    # 判断是否违反松弛约束
    if max_relax > relax:
        coneObj.release_nodes(inst_to_nodeObj)
        return None, None, new_gates, coneObj, False
    # 读取优化后逻辑锥信息
    abc_tool.empty()
    abc_command = f'read -m {run_path}/cone_hmx_{coneObj.id}_size_opt.v;topo;stime;'
    output = abc_tool.execute_command(abc_command)
    result = re.findall(r'Gates\s*=\s*(\d+).+?Cap\s*=\s*([\d.]+)\s+ff.+?Area\s*=\s*([\d.]+).+?Delay\s*=\s*([\d.]+)\s+ps', output)
    post_gates = result[0][0]
    post_cap = result[0][1]
    post_area = result[0][2]
    post_delay = result[0][3]
    with open(f'{run_path}/cone_hmx_{coneObj.id}_report.txt', 'w') as f:
        header = "{:<10} | {:<10} | {:<10}"
        divider = "-----------|------------|------------"
        row = "{:<10} | {:>10} | {:>10}"
        f.write(header.format("Metric", "Original", "Optimized") + "\n")
        f.write(divider + "\n")
        f.write(row.format("Gates", f"{pre_gates}", f"{post_gates}") + "\n")
        f.write(row.format("Cap(ff)", f"{pre_cap}", f"{post_cap}") + "\n")
        f.write(row.format("Area", f"{pre_area}", f"{post_area}") + "\n")
        f.write(row.format("Delay(ps)", f"{pre_delay}", f"{post_delay}") + "\n")
    delay_info = (float(pre_delay), float(post_delay))
    gate_info = (int(pre_gates), int(post_gates))
    # 统计新单元应用的数量
    if en_count:
        abc_tool.empty() # 清理ABC工作区
        abc_command = f'read -m {run_path}/cone_hmx_{coneObj.id}_size_opt.v;print_gates;'
        output = abc_tool.execute_command(abc_command)
        result = re.findall(r'(\w+).+?Instance\s*=\s*(\d+)', output)
        for gate in result:
            if gate[0].startswith('HP'):
                if gate[0] not in new_gates:
                    new_gates[gate[0]] = 0
                new_gates[gate[0]] += int(gate[1])
    return gate_info, delay_info, new_gates, coneObj, True

def main_remap(design:str, num_pre_group:int, distence_threshold:int, pathId_to_pathObj:dict, inst_to_nodeObj:dict, cell_to_cellObj:dict, libs:list[str], en_count:bool, relax:int, output_dir:str | os.PathLike='remap_results', abc_executable:str='abc', sta_executable:str='sta') -> tuple[dict, dict]:
    """逻辑锥处理、重映射主函数"""
    # 将路径分组，每组包含num_pre_group条路径
    group_num = math.ceil(len(pathId_to_pathObj) / num_pre_group)
    batchs = {}
    for k, v in pathId_to_pathObj.items():
        batchId = (k-1) // num_pre_group
        if batchId not in batchs:
            batchs[batchId] = []
        batchs[batchId].append(v)

    if len(batchs) != group_num:
        assert False, 'group_num is not equal to len(batchs)'

    coneId_to_coneObj = {}
    coneId = 0
    for batchId, paths in batchs.items():
        # 合并本批次的路径的公共节点
        merged_paths = merge_key_path(paths, inst_to_nodeObj)
        # 切割本批次的路径，得到初始逻辑锥
        for sub_graph in merged_paths.values():
            coneId_to_coneObj, coneId = cut_merged_key_path(distence_threshold, coneId_to_coneObj, coneId, sub_graph, inst_to_nodeObj)
    # 初始逻辑锥进行完整逻辑锥构造、逻辑重映射
    abc_tool = ABC(libs, executable=abc_executable)
    sta_tool = STA(libs, executable=sta_executable)
    run_dir = Path(output_dir) / design
    run_path = run_dir.as_posix()
    if not run_dir.exists():
        run_dir.mkdir(parents=True)
    else:
        shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True)
    delay_report = {}
    gate_report = {}
    new_gates = {}
    del_coneId = []
    for coneId, coneObj in tqdm(
            coneId_to_coneObj.items(),
            desc="Processing cones",
            unit="cone",
            total=len(coneId_to_coneObj)):
        coneObj = get_cone(distence_threshold, coneObj, inst_to_nodeObj, cell_to_cellObj)
        coneObj.update_wires(inst_to_nodeObj)
        gate_info, delay_info, new_gates, coneObj, replaced = remap(design, coneObj, inst_to_nodeObj, abc_tool, sta_tool, new_gates, en_count, cell_to_cellObj, relax, output_dir)
        if not replaced:
            del_coneId.append(coneId)
            continue
        delay_report[coneId] = delay_info[0] - delay_info[1]
        gate_report[coneId] = gate_info[0] - gate_info[1]
        coneId_to_coneObj[coneId] = coneObj
        abc_tool.empty() # 清理ABC工作区
    for coneId in del_coneId:
        del coneId_to_coneObj[coneId]
    abc_tool.kill()
    sta_tool.kill()

    delay_report = dict(sorted(delay_report.items(), key=lambda item: item[1], reverse=True))
    total_delay_imp = 0
    for delay_num in delay_report.values():
        total_delay_imp += delay_num
    avg_delay_imp = total_delay_imp / len(delay_report) if len(delay_report) != 0 else 0
    log(f'total delay imp: {total_delay_imp}')
    log(f'avg delay imp: {avg_delay_imp}')
    with open(f'{run_path}/delay_report.json', 'w') as f:
        json.dump(delay_report, f, indent=4)
        f.write(f'\ntotal delay imp: {total_delay_imp}\n')
        f.write(f'avg delay imp: {avg_delay_imp}\n')
        log(f'delay_report.json saved at {run_path}/delay_report.json')

    gate_report = dict(sorted(gate_report.items(), key=lambda item: item[1], reverse=True))
    total_gate_imp = 0
    for gate_num in gate_report.values():
        total_gate_imp += gate_num
    avg_gate_imp = total_gate_imp / len(gate_report) if len(gate_report) != 0 else 0
    log(f'total gate imp: {total_gate_imp}')
    log(f'avg gate imp: {avg_gate_imp}')
    with open(f'{run_path}/gate_report.json', 'w') as f:
        json.dump(gate_report, f, indent=4)
        f.write(f'\ntotal gate imp: {total_gate_imp}\n')
        f.write(f'avg gate imp: {avg_gate_imp}\n')
        log(f'gate_report.json saved at {run_path}/gate_report.json')

    with open(f'{run_path}/new_gates.json', 'w') as f:
        json.dump(new_gates, f, indent=4)
        log(f'new_gates.json saved at {run_path}/new_gates.json')

    return coneId_to_coneObj

def main_rewrite(module_to_moduleObj:dict, coneId_to_coneObj:dict, inst_to_nodeObj:dict, def_file:str, design:str, debug_num:int=-1, output_dir:str | os.PathLike='remap_results') -> None:
    """重写网表"""
    run_path = (Path(output_dir) / design).as_posix()
    cone_ids = []
    cone_infos = []
    total_new_gates_num = 0
    replaced_gates = []
    for coneId, coneObj in coneId_to_coneObj.items():
        if debug_num == 0:
            continue
        if debug_num > 0:
            debug_num -= 1
        # 将逻辑锥对应的信息加入到module集合中
        cone_ids.append(coneId)
        cone_infos.append(coneObj.info)
        # 记录被替换的节点
        for nodename in coneObj.nodes:
            nodeObj = inst_to_nodeObj[nodename]
            replaced_gates.append(nodeObj.full_inst)
        total_new_gates_num += len(coneObj.new_gates)
        # 将逻辑锥所属module的相关实例单元删除
        moduleObj = module_to_moduleObj[coneObj.module]
        for nodeName in coneObj.nodes:
            nodeObj = inst_to_nodeObj[nodeName]
            if nodeObj.inst not in moduleObj.inst_to_instInfo:
                assert False
            del moduleObj.inst_to_instInfo[nodeObj.inst]
        # 将逻辑锥实例化到对应module中
        cone_inst_info = f'cone_hmx_{coneId}_inst (\n'
        lenth = len(coneObj.port_map)
        for port, wire in coneObj.port_map.items():
            if lenth == 1:
                cone_inst_info += f'\t\t.{port}({wire}));'
            else:
                cone_inst_info += f'\t\t.{port}({wire}),\n'
            lenth -= 1
        moduleObj.inst_to_instInfo[f'cone_hmx_{coneId}_inst'] = (f'cone_hmx_{coneId}', cone_inst_info)
    
    # 输出被替换的节点
    with open(f'{run_path}/replaced_gates.json', 'w') as f:
        json.dump(replaced_gates, f, indent=4)
        log(f'total {len(replaced_gates)} gates replaced with {total_new_gates_num} gates')
        log(f'saved at {run_path}/replaced_gates.json')

    # 写入新网表
    time_info = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    with open(f'{run_path}/{design}_{time_info}.v', 'w') as f:
        for cone_info in cone_infos:
            f.write(cone_info+'\n')
        for moduleObj in module_to_moduleObj.values():
            f.write(f'module {moduleObj.name} (\n')
            for i in range(len(moduleObj.ports)):
                port_name = moduleObj.ports[i]
                if i == len(moduleObj.ports) - 1:
                    f.write(f'\t{port_name});\n')
                else:
                    f.write(f'\t{port_name},\n')

            for input_name, end_to_start in moduleObj.inputs.items():
                f.write(f'\tinput {end_to_start} {input_name};\n')
            for output_name, end_to_start in moduleObj.outputs.items():
                f.write(f'\toutput {end_to_start} {output_name};\n')
            for wire_name, end_to_start in moduleObj.wires.items():
                f.write(f'\twire {end_to_start} {wire_name};\n')
            for line in moduleObj.assign:
                f.write(f'\t{line}\n')

            for inst_info in moduleObj.inst_to_instInfo.values():
                f.write(f'\t{inst_info[0]} {inst_info[1]}\n')
            f.write('endmodule\n\n')

    log('rewrite complete')
