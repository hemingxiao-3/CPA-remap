import re
import datetime
from .models import Node, Path, Cell, Wire, Module

def log(info):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] : {info}")

def proc_cell_name(cell_name):
    cell_name = cell_name.rsplit("_", 1)[0]
    return cell_name

def parse_unit_verilog(filename: str) -> dict:
    """解析标准单元行为描述文件"""
    
    def replace_variables(expr, symbol_map):
        """ 递归替换表达式中的中间变量 """
        replaced = True
        while replaced:
            replaced = False
            # 按变量名长度降序排序避免部分匹配
            for var in sorted(symbol_map.keys(), key=lambda x: -len(x)):
                pattern = r'\b' + re.escape(var) + r'\b'
                if re.search(pattern, expr):
                    expr = re.sub(pattern, f'({symbol_map[var]})', expr)
                    replaced = True
        return expr

    with open(filename, 'r') as f:
        lines = f.readlines()

    cell_to_cellObj = {}
    current_cell = None
    flag = False
    symbol_map = {} # 存储中间变量表达式
    output_exprs = [] # 存储输出端口的原始表达式

    for line in lines:
        line = line.strip()

        # 匹配模块定义
        module_match = re.match(r'module\s+(\w+)\s*\(', line)
        if module_match:
            cell_name = proc_cell_name(module_match.group(1))
            if cell_name not in cell_to_cellObj:
                current_cell = Cell(cell_name)
                cell_to_cellObj[cell_name] = current_cell
                if cell_name.startswith(('DFF')):
                    current_cell.is_comb = False
                flag = True
                symbol_map = {} # 重置中间变量表
                output_exprs = [] # 重置输出端口表达式
            continue

        if not flag:
            continue

        # 匹配输入端口
        input_match = re.match(r'input\s+(.+);', line)
        if input_match:
            ports = [p.strip() for p in input_match.group(1).split(',')]
            for port in ports:
                current_cell.inputs.append(port)
                if port in {'clk', 'CK', 'CKN', 'nclk'}:
                    current_cell.is_comb = False
            continue

        # 匹配输出端口
        output_match = re.match(r'output\s+(.+);', line)
        if output_match:
            ports = [p.strip() for p in output_match.group(1).split(',')]
            for port in ports:
                current_cell.outputs.append(port)
                if port in {'clk', 'CK', 'CKN', 'nclk'}:
                    current_cell.is_comb = False
                if cell_name.startswith('PULL0'):
                    current_cell.functions.append(f"{port} = 0")
                elif cell_name.startswith('PULL1'):
                    current_cell.functions.append(f"{port} = 1")
            continue

        # 匹配门级实例化（关键修改部分）
        gate_match = re.match(r'\s*(\w+)\s+\w*\s*\(([^)]+)\)\s*;', line)
        if gate_match and current_cell.is_comb:
            gate_type = gate_match.group(1).lower()
            ports = [p.strip() for p in gate_match.group(2).split(',')]

            if len(ports) < 2:
                assert False, f"Unexpected operator type: {gate_type} with less than 2 ports"

            output_port = ports[0]
            inputs = ports[1:]

            # 生成原始表达式
            if gate_type in {'xor', 'and', 'or'}:
                operator = {'xor':'^', 'and':'&', 'or':'|'}[gate_type]
                raw_expr = f"{operator}".join(inputs)
            elif gate_type == 'not' and len(inputs) == 1:
                raw_expr = f"~{inputs[0]}"
            elif gate_type == 'buf' and len(inputs) == 1:
                raw_expr = inputs[0]
            elif gate_type == 'nand':
                raw_expr = f"&".join(inputs)
                raw_expr = f"~({raw_expr})"
            elif gate_type == 'nor':
                raw_expr = f"|".join(inputs)
                raw_expr = f"~({raw_expr})"
            elif gate_type == 'xnor':
                raw_expr = f"^".join(inputs)
                raw_expr = f"~({raw_expr})"
            elif gate_type == 'udp_mux' or gate_type == 'udp_mux2':
                raw_expr = f"(~{inputs[2]}&{inputs[0]})|({inputs[2]}&{inputs[1]})"
            elif gate_type == 'udp_mux4':
                raw_expr = f"(~{inputs[4]}&~{inputs[5]}&{inputs[0]})|({inputs[4]}&~{inputs[5]}&{inputs[1]})|(~{inputs[4]}&{inputs[5]}&{inputs[2]})|({inputs[4]}&{inputs[5]}&{inputs[3]})"
            else:
                assert False, f"Unexpected operator type: {gate_type}"

            # 分类存储表达式
            if output_port in current_cell.outputs:
                output_exprs.append( (output_port, raw_expr) )
            else:
                symbol_map[output_port] = raw_expr

        # 后处理：替换中间变量
        if line.startswith('endmodule') and current_cell.is_comb and flag:
            flag = False
            for output_port, raw_expr in output_exprs:
                processed_expr = replace_variables(raw_expr, symbol_map)
                current_cell.functions.append(f"{output_port} = {processed_expr}")

    log(f'Total {len(cell_to_cellObj)} cells parsed')

    return cell_to_cellObj

def parse_lib(filenames:list[str]) -> dict:
    cell_to_cellObj = {}
    for filename in filenames:
        log(f'Parsing {filename} ...')

        with open(filename, 'r') as f:
            lines = f.readlines()

        flag = False
        for line in lines:
            line = line.strip()

            result = re.match(r'cell\s+\((\w+)\)\s*\{', line)
            if result:
                full_cell = result.group(1)
                cell = proc_cell_name(full_cell)
                if cell not in cell_to_cellObj:
                    cur_cellObj = Cell(cell)
                    cell_to_cellObj[cell] = cur_cellObj
                    if full_cell.startswith(('DFF')):
                        cur_cellObj.is_comb = False
                    flag = True
                else:
                    flag = False
                cell_to_cellObj[cell].full_names.append(full_cell)
                version = full_cell.rsplit("_", 1)[1]
                cell_to_cellObj[cell].version_to_cell[version] = full_cell
                continue

            if not flag:
                continue

            result = re.match(r'pin\s+\((\w+)\)', line)
            if result:
                cur_pin = result.group(1)
                if cur_pin in {'clk', 'CK', 'CKN', 'nclk'}:
                    cur_cellObj.is_comb = False
                continue

            result = re.match(r'direction\s*:\s*"?([^"]*)"?;', line)
            if result:
                cur_direction = result.group(1)
                if cur_direction == "input":
                    cur_cellObj.inputs.append(cur_pin)
                elif cur_direction == "output":
                    cur_cellObj.outputs.append(cur_pin)
                continue

            result = re.match(r'function\s*:\s*"([^"]*)";', line)
            if result:
                fun = cur_pin + "=" + result.group(1)
                cur_cellObj.functions.append(fun)

    log(f'Total {len(cell_to_cellObj)} cells parsed')

    return cell_to_cellObj

def parse_rpt(filename:str) -> dict:
    """解析时序报告，提取关键路径"""
    with open(filename, 'r') as f:
        lines = f.readlines()

    pathId_to_pathObj = {}
    cur_pathId = 0
    for line in lines:
        line = line.strip()
        
        if line.startswith('Startpoint'):
            cur_pathId += 1
            pathId_to_pathObj[cur_pathId] = Path(cur_pathId)
            continue

        result = re.search(r'\d+\.\d+\s+\d+\.\d+\s+[v\^]\s+(\w+)\/\w+\s+\(\w+\)', line)
        if result:
            if result.group(1) not in pathId_to_pathObj[cur_pathId].nodes:
                pathId_to_pathObj[cur_pathId].nodes.append(result.group(1))

    log(f"Total {len(pathId_to_pathObj)} VIOLATED paths found")

    return pathId_to_pathObj

def parse_def(filename:str) -> dict:
    """解析def文件，提取实例位置信息"""
    with open(filename, 'r') as f:
        lines = f.readlines()
    
    inst_to_location = {}
    flag = False
    for line in lines:
        line = line.strip()
        # 处理UNITS
        if line.startswith('UNITS DISTANCE MICRONS'):
            units = int(line.split()[3])
            continue
        # 处理COMPONENTS
        if line.startswith('COMPONENTS'):
            flag = True
            continue
        # 处理END COMPONENTS
        if line.startswith('END COMPONENTS'):
            flag = False
            break
        # 处理COMPONENTS中的内容
        if flag:
            if line.startswith('-'):
                inst_name = line.split()[1]
            result = re.search(r'PLACED\s*\(\s*(\d+)\s*(\d+)\s*\)', line)
            if result:
                x = int(result.group(1)) / units
                y = int(result.group(2)) / units
                inst_to_location[inst_name] = (x, y)
                continue
            result = re.search(r'FIXED\s*\(\s*(\d+)\s*(\d+)\s*\)', line)
            if result:
                x = int(result.group(1)) / units
                y = int(result.group(2)) / units
                inst_to_location[inst_name] = (x, y)
                continue

    log(f"Total {len(inst_to_location)} instances location parsed")

    return inst_to_location

def parse_verilog(topModule:str, filename:str, inst_to_location:dict, cell_to_cellObj:dict) -> tuple[dict, dict]:
    """解析网表文件，提取实例信息，并建立实例连接关系"""
    with open(filename, 'r') as f:
        data = f.read()
    inst_to_nodeObj = {}
    module_to_moduleObj = {}
    # 提取模块信息
    not_found_cells = set()
    module_to_moduleInfo = {}
    modules = re.findall(r'(module\s+.*?endmodule)', data, re.DOTALL) # 模块信息
    for moduleInfo in modules: # 建立模块信息字典
        name = re.search(r'module\s+(\w+)\s*\(', moduleInfo).group(1)
        module_to_moduleInfo[name] = moduleInfo
    # 创建实例类，并创建实例连接关系
    module_lst = [topModule] # 模块处理队列，从顶层模块开始
    level_lst = [''] # 模块层次队列，与模块处理队列对应
    while module_lst:
        module = module_lst.pop()
        pre_level = level_lst.pop()
        if module not in module_to_moduleInfo:
            assert False, f"Module {module} not found in verilog file"
        moduleInfo = module_to_moduleInfo[module]
        cur_level = pre_level + '/' if pre_level else ''
        new_module = Module(module)
        module_to_moduleObj[module] = new_module

        # 解析输入端口
        input_infos = re.findall(r'input\s+((?:\[\d+:\d+\])*)\s*(\w+);', moduleInfo, re.DOTALL)
        for input_info in input_infos:
            end_to_start = input_info[0]
            input_name = input_info[1]
            if input_name not in new_module.inputs:
                new_module.ports.append(input_name)
                new_module.inputs[input_name] = end_to_start
            else:
                assert False, f"Duplicate input: {input_name}"

        # 解析输出端口
        output_infos = re.findall(r'output\s+((?:\[\d+:\d+\])*)\s*(\w+);', moduleInfo, re.DOTALL)
        for output_info in output_infos:
            end_to_start = output_info[0]
            output_name = output_info[1]
            if output_name not in new_module.outputs:
                new_module.ports.append(output_name)
                new_module.outputs[output_name] = end_to_start
            else:
                assert False, f"Duplicate output: {output_name}"

        # 解析内部连接
        wire_infos = re.findall(r'wire\s+((?:\[\d+:\d+\])*)\s*(.+);', moduleInfo)
        for wire_info in wire_infos:
            end_to_start = wire_info[0]
            wire_name = wire_info[1]
            if wire_name not in new_module.wires:
                new_module.wires[wire_name] = end_to_start
            else:
                assert False, f"Duplicate wire: {wire_name}"

        # 解析assign语句
        assign_wires = set()
        output_infos = re.findall(r'(assign\s+.+?;)', moduleInfo, re.DOTALL)
        for output_info in output_infos:
            new_module.assign.append(output_info)
            result = re.search(r'assign\s+([^=]+)=\s+([^;]+);', output_info)
            assign_wires.add(result.group(1))
            assign_wires.add(result.group(2))

        # 提取实例信息
        cut_wires = set()
        inst_list = re.findall(r'(\w+\s+\S+\s+\(\s*\.[^;]+;)', moduleInfo, re.DOTALL)
        wire_to_wireObj = {} # module线字典
        for inst in inst_list:
            result = re.search(r'(\w+)\s+(\S+)\s+\(\s*\.', inst)
            first_name = result.group(1) # 实例单元名
            inst_name = result.group(2) # 实例名
            cell_name = proc_cell_name(first_name) # 处理后标准单元格式
            node_name = cur_level + inst_name # 实例包含层次的全称
            instInfo = re.search(r'\w+\s+(\S+\s+\(\s*\.[^;]+;)', inst, re.DOTALL).group(1)
            new_module.inst_to_instInfo[inst_name] = (first_name, instInfo)
            if first_name.startswith('sa') or first_name.startswith('fakeram'): # 不考虑这种寄存器，类似IP
                wire_list = re.findall(r'\.\w+\(([^)]*)\)', inst, re.DOTALL)
                for wire in wire_list:
                    if '{' in wire:
                        wires = wire.replace('{', '').replace('}', '').split(',')
                        for w in wires:
                            cut_wires.add(w.strip())
                    else:
                        cut_wires.add(wire)
                continue
            elif first_name in module_to_moduleInfo: # 这是一个模块实例，添加到队列中后续处理
                wire_list = re.findall(r'\.\w+\(([^)]*)\)', inst, re.DOTALL)
                for wire in wire_list:
                    if '{' in wire:
                        wires = wire.replace('{', '').replace('}', '').split(',')
                        for w in wires:
                            cut_wires.add(w.strip())
                    else:
                        cut_wires.add(wire)
                module_lst.append(first_name)
                level_lst.append(node_name)
            else: # 这是一个标准单元实例，创建节点类
                if cell_name not in cell_to_cellObj:
                    assert False, f"Cell {cell_name} not found in lib"
                if first_name not in cell_to_cellObj[cell_name].full_names:
                    if first_name not in not_found_cells:
                        not_found_cells.add(first_name)
                        log(f'cell {first_name} not found in lib, replaced with {cell_to_cellObj[cell_name].full_names[0]}')
                    first_name = cell_to_cellObj[cell_name].full_names[0]
                new_module.inst_to_instInfo[inst_name] = (first_name, instInfo)
                if node_name in inst_to_nodeObj:
                    assert False
                newNode = Node(node_name)
                inst_to_nodeObj[node_name] = newNode
                newNode.inst = inst_name
                newNode.cell = cell_name
                newNode.full_cell = first_name
                newNode.module = module
                # 获取节点位置
                if node_name in inst_to_location:
                    newNode.location = inst_to_location[node_name]
                # else:
                #     assert False, f'{node_name} can not find location'
                # 记录实例之间的连接关系，每一层用一个字典记录线与节点的关系
                wire_list = re.findall(r'\.(\w+)\(([^)]*)\)', inst, re.DOTALL)
                for (port_name, wire_name) in wire_list:
                    full_port_name = node_name + ':' + port_name
                    if port_name in cell_to_cellObj[cell_name].inputs:
                        port_direction = 'input'
                    elif port_name in cell_to_cellObj[cell_name].outputs:
                        port_direction = 'output'
                    else:
                        assert False, 'can not find port name'
                    if wire_name == '': # 端口悬空的情况
                        inst_to_nodeObj[node_name].disconnect.append(port_name)
                        continue
                    if wire_name not in wire_to_wireObj:
                        wire_to_wireObj[wire_name] = Wire(wire_name)
                    wire_to_wireObj[wire_name].add_port(full_port_name, port_direction)
        # 获取完当前层次所有线与节点关系后，将节点之间的连接关系添加到节点类中
        for wire in wire_to_wireObj.values():
            real_wire = wire.name.split('[', 1)[0]
            pre_port = wire.from_pre if wire.from_pre else None
            pre_node = inst_to_nodeObj[pre_port.split(':')[0]] if pre_port else None
            if not wire.to_nxt:
                pre_node.output_wires.append((pre_port, None, wire.name))
            for port_name in wire.to_nxt:
                nxt_node = inst_to_nodeObj[port_name.split(':')[0]]
                pair = (pre_port, port_name, wire.name)
                if pre_node:
                    pre_node.output_wires.append(pair)
                nxt_node.input_wires.append(pair)
            if pre_node and wire.to_nxt and (real_wire in new_module.outputs or wire.name in assign_wires or wire.name in cut_wires):
                pre_node.output_wires.append((pre_port, None, wire.name))

    log(f"Total {len(module_to_moduleObj)} modules parsed")
    log(f"Total {len(inst_to_nodeObj)} instances parsed")

    return inst_to_nodeObj, module_to_moduleObj

def parse_rpt_new(filename:str) -> dict:
    """解析时序报告，提取关键路径"""
    with open(filename, 'r') as f:
        lines = f.readlines()

    pathId_to_pathObj = {}
    cur_pathId = None
    for line in lines:
        line = line.strip()
        if "Aocv" in line or "Stage" in line or "Count" in line: # 跳过这些行
            continue
        # 处理met path行
        result = re.search(r"Path\s+(\d+):\s+MET", line)
        if result:
            break
        # 处理violated path行
        result = re.search(r"Path\s+(\d+):\s+VIOLATED", line)
        if result:
            instName = None
            cur_pathId = int(result.group(1))
            new_path = Path(cur_pathId)
            pathId_to_pathObj[cur_pathId] = new_path
            continue
        # 处理RT行
        result = re.search(r"= Required Time\s+(-?\d+.\d+)", line)
        if result:
            RT = float(result.group(1))
            if pathId_to_pathObj[cur_pathId].RT is not None:
                assert False
            pathId_to_pathObj[cur_pathId].RT = RT
            continue
        # 处理AT行
        result = re.search(r"- Arrival Time\s+(-?\d+.\d+)", line)
        if result:
            AT = float(result.group(1))
            pathId_to_pathObj[cur_pathId].AT = AT
            continue
        # 处理BAT行
        result = re.search(r"= Beginpoint Arrival Time\s+(-?\d+.\d+)", line)
        if result:
            BAT = float(result.group(1))
            pathId_to_pathObj[cur_pathId].BAT = BAT
            continue
        # 处理最后一个寄存器节点
        result = re.match(r"\+\-+\+", line)
        if result and instName is not None:
            new_path.nodes.append(instName)
            continue
        # 处理关键路径节点信息
        result = re.findall(r"\|([^|]+)", line)
        if len(result) == 13:
            if result[7].strip() != "": # 这是抵达该节点的线延迟，从这里开始记录关键路径节点
                instName = result[0].strip()
                location = result[9].strip()[1:-1].split(", ")
                flag = True # 防止重复添加实例名字

            elif result[9].strip() == "" and flag: # 这是考虑到实例名字太长导致的换行
                instName += result[0].strip()

            elif "->" in line: # 这是一个实例内部延迟
                new_path.nodes.append(instName)
                flag = False
    # 更新路径延迟
    for path in pathId_to_pathObj.values():
        path.update_delay()

    log(f"Total {len(pathId_to_pathObj)} VIOLATED paths found")

    return pathId_to_pathObj
