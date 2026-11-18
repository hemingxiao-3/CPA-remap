import re

# 拓扑网络节点类
class Node:
    def __init__(self, full_inst):
        self.full_inst = full_inst # 实例全名，加入了模块信息，具备唯一性
        self.inst = None # 实例名，不加入模块信息，不具备唯一性
        self.cell = None # 标准单元缩减名，表示功能
        self.full_cell = None # 标准单元全名
        self.input_wires = [] # 输入端口对：('上级实例名:上级端口名' or None, '本级实例名:本端口名', 线名)
        self.output_wires = [] # 输出端口对：('本级实例名:本端口名', '下级实例名:下级端口名' or None, 线名)
        self.disconnect = [] # 悬空端口：端口名
        self.location = None # 节点位置
        self.cone_id = None # 节点所属的cone序号
        self.module = None # 节点所属模块名

# 关键路径类
class Path:
    def __init__(self, id):
        self.id = id # 路径序号
        self.RT = None # required time
        self.AT = None # arrival time
        self.BAT = None # begipoint arrival time
        self.delay = None # 路径延迟
        self.wire_delay = [] # 各个节点之间的线延迟
        self.nodes = [] # 顺序节点实例名字列表

    def update_delay(self):
        self.delay = self.AT - self.BAT

# 标准单元类
class Cell:
    def __init__(self, name):
        self.name = name # 标准单元缩减名，仅表示功能
        self.full_names = [] # 标准单元全名列表
        self.version_to_cell = {} # key为版本名，value为全名
        self.is_comb = True # 是否为组合逻辑单元
        self.inputs = [] # 输入端口列表
        self.outputs = [] # 输出端口列表
        self.functions = [] # 逻辑表达式列表

# 连接线类
class Wire:
    def __init__(self, name):
        self.name = name # 连接线名
        self.to_nxt = [] # 连接线所连接的下级节点端口名列表
        self.from_pre = None # 连接线所连接的上级节点端口名
        self.output_wire = False
        self.input_wire = False
        self.new_name = None

    def add_port(self, portName, portDirection):
        if portDirection == 'input':
            self.to_nxt.append(portName)
        elif portDirection == 'output':
            if self.from_pre == None or self.from_pre == portName:
                self.from_pre = portName
            else:
                assert False, 'wire has more than one input port'
        else:
            assert False, 'port direction error'

# 逻辑锥类
class Cone:
    def __init__(self, id):
        self.id = id # 逻辑锥序号
        self.nodes = [] # 逻辑锥所包含的节点实例名列表
        self.input_wires = [] # 输入端口对：('上级实例名:上级端口名' or None, '本级实例名:本端口名', 线名)
        self.output_wires = [] # 输出端口对：('本级实例名:本端口名', '下级实例名:下级端口名' or None, 线名)
        self.root_nodes = [] # 逻辑锥的根节点实例名列表
        self.module = None # 逻辑锥所属的模块名
        self.port_map = {} # 逻辑锥的端口映射，key为锥内端口名，value为锥外连接名
        self.info = '' # 逻辑锥对应的module信息
        self.new_gates = {} # 新逻辑锥实例名:标准单元名

    def release_nodes(self, inst_to_nodeObj):
        for node in self.nodes:
            inst_to_nodeObj[node].cone_id = None

    def update_new_gates(self):
        cur_level = self.nodes[0].rsplit('/', 1)[0] + f'/cone_hmx_{self.id}_inst/' if '/' in self.nodes[0] else f'cone_hmx_{self.id}_inst/'
        self.new_gates = {}
        result = re.findall(r'(\w+)\s+(\w+)\s*\(\s*\.', self.info)
        for (cell_name, inst_name) in result:
            inst_name = cur_level + inst_name
            self.new_gates[inst_name] = cell_name

    def add_node(self, node):
        self.nodes.append(node)

    def update_wires(self, inst_to_nodeObj): # 更新逻辑锥的输入输出端口对
        self.input_wires = []
        self.output_wires = []
        for node in self.nodes:
            nodeObj = inst_to_nodeObj[node]
            for wire in nodeObj.input_wires:
                # 如果没有上级节点，或者上级节点不在逻辑锥内，则该线为逻辑锥的输入线
                if wire[0] == None or wire[0].split(':')[0] not in self.nodes:
                    self.input_wires.append(wire)
            for wire in nodeObj.output_wires:
                # 如果没有下级节点，或者下级节点不在逻辑锥内，则该线为逻辑锥的输出线
                if wire[1] == None or wire[1].split(':')[0] not in self.nodes:
                    self.output_wires.append(wire)

    def get_all_connected_nodes(self): # 获取逻辑锥所有连接的节点实例名列表，包括根节点所连接的输出节点
        connected_nodes = [] # 逻辑锥所有连接的节点实例名列表
        cone_nodes = [] # 对应于逻辑锥内与之相连接的节点实例名列表
        for wire in self.input_wires:
            if wire[0] != None:
                connected_nodes.append(wire[0].split(':')[0])
                cone_nodes.append(wire[1].split(':')[0])
        for wire in self.output_wires:
            if wire[1] != None:
                connected_nodes.append(wire[1].split(':')[0])
                cone_nodes.append(wire[0].split(':')[0])
        return connected_nodes, cone_nodes
    
    def update_root_nodes(self, inst_to_nodeObj): # 更新逻辑锥的根节点实例名列表，需要在获取完整逻辑锥之前执行
        self.root_nodes = []
        for node in self.nodes:
            nodeObj = inst_to_nodeObj[node]
            flag = True
            for wire in nodeObj.output_wires:
                if wire[1] != None and wire[1].split(':')[0] in self.nodes:
                    flag = False
                    break
            if flag:
                self.root_nodes.append(node)

    def get_connected_nodes(self): # 获取逻辑锥所连接的节点实例名列表，不包括根节点所连接的输出节点
        connected_nodes = [] # 逻辑锥所连接的节点实例名列表
        cone_nodes = [] # 对应于逻辑锥内与之相连接的节点实例名列表
        for wire in self.input_wires:
            if wire[0] != None:
                connected_nodes.append(wire[0].split(':')[0])
                cone_nodes.append(wire[1].split(':')[0])
        return connected_nodes, cone_nodes

class Module:
    def __init__(self, name):
        self.name = name
        self.ports = []
        self.inputs = {} # name: '[end:start]'
        self.outputs = {} # name: '[end:start]'
        self.wires = {} # name: '[end:start]'
        self.assign = []
        self.inst_to_instInfo = {} # 实例名到实例信息的映射
