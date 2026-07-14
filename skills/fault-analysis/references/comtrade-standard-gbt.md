# GB/T 14598.24-2017 COMTRADE 标准格式

> 量度继电器和保护装置第24部分：电力系统暂态数据交换(COMTRADE)通用格式
>
> IEC 60255-24:2013，代替GB/T22386-2008

---

## 文件结构

每个COMTRADE记录由4个相关文件组成（文件名相同，扩展名不同）：

| 文件 | 扩展名 | 必需 | 说明 |
|------|--------|------|------|
| 头文件 | `.HDR` | 否 | ASCII文本，可读性描述信息 |
| 配置文件 | `.CFG` | 是 | ASCII，定义数据格式 |
| 数据文件 | `.DAT` | 是 | ASCII/Binary/Binary32/Float32 |
| 信息文件 | `.INF` | 否 | INI格式，扩展信息 |

**单文件格式**：`.CFF` - 包含上述4个分区的单文件

---

## CFG 配置文件格式

### 第1行：站名、设备标识、版本

```
station_name,rec_dev_id,rev_year
```

| 字段 | 说明 | 必需 |
|------|------|------|
| station_name | 厂站名称（1-64字符） | 是 |
| rec_dev_id | 记录装置标识（1-64字符） | 是 |
| rev_year | COMTRADE版本：1991/1999/2013 | 是 |

### 第2行：通道总数

```
TT,#A,#D
```

| 字段 | 说明 |
|------|------|
| TT | 通道总数 = #A + #D |
| #A | 模拟通道数量（如 8A） |
| #D | 状态通道数量（如 16D） |

### 模拟通道定义（每个通道一行）

```
An,ch_id,ph,ccbm,uu,a,b,skew,min,max,primary,secondary,PS
```

| 字段 | 说明 | 示例 |
|------|------|------|
| An | 通道索引（1起始） | 1 |
| ch_id | 通道名称（1-128字符） | 保护电流A相 |
| ph | 相别标识 | A |
| ccbm | 被监视元件 | 线路 |
| uu | 单位 | A, V, kV |
| a | 增益系数 | 0.01 |
| b | 偏移量 | 0 |
| skew | 时滞（微秒） | 0 |
| min | 最小值 | -32768 |
| max | 最大值 | 32767 |
| primary | 互感器一次系数 | 800 |
| secondary | 互感器二次系数 | 5 |
| PS | 一次/二次标识 | P 或 S |

**工程值转换公式**：`工程值 = a × 原始值 + b`

### 状态通道定义（每个通道一行）

```
Dn,ch_id,ph,ccbm,y
```

| 字段 | 说明 |
|------|------|
| Dn | 状态通道索引（1起始） |
| ch_id | 通道名称 |
| ph | 相别标识 |
| ccbm | 被监视元件 |
| y | 正常状态（0或1） |

### 电网频率

```
lf
```

- `lf`：电网频率，单位Hz（如 50）

### 采样率信息

```
nrates
samp,endsamp
```

| 字段 | 说明 |
|------|------|
| nrates | 采样率数量 |
| samp | 采样率（Hz），0表示变采样率 |
| endsamp | 该采样率下的末点采样序号 |

示例（固定10kHz采样，采样点1-10000）：
```
1
10000,10000
```

示例（变采样率）：
```
0
0,10000
```

### 时间标记

```
dd/mm/yyyy,Hh:Mm:Ss.ssssss
dd/mm/yyyy,Hh:Mm:Ss.ssssss
```

第一行：第一个数据点时间
第二行：触发点时间

### 数据文件类型

```
time_mult,ft
```

| 字段 | 说明 |
|------|------|
| time_mult | 时标倍率因子（通常为1） |
| ft | 数据格式：ASCII/BINARY/BINARY32/FLOAT32 |

---

## DAT 数据文件格式

### ASCII 格式

每行一个采样点，逗号分隔：

```
n,timestamp,A1,A2,...,Ak,D1,D2,...,Dm
```

| 字段 | 说明 |
|------|------|
| n | 采样序号（1-9999999999） |
| timestamp | 时标（微秒或纳秒） |
| A1~Ak | 模拟通道值 |
| D1~Dm | 状态通道值（0或1） |

**示例**：
```
1,0,1000,-200,300,400,500,600,0,0,0,0,1,1
2,100,1005,-195,305,395,505,595,0,0,0,0,1,1
```

### Binary 格式（16位）

每采样点结构：

```
┌─────────────┬─────────────┬─────────────┬─────────────┐
│  n (4字节)  │ timestamp   │ 模拟量      │ 状态量      │
│  采样序号   │ (4字节)     │ (2字节×N)   │ (2字节×M)   │
│  小端序     │ 微秒/纳秒   │ 有符号整数  │ 打包位      │
└─────────────┴─────────────┴─────────────┴─────────────┘
```

**字节序**：小端序（LSB在前）
**缺失数据**：模拟量用最大负值（0x8000）代替
**状态量打包**：每16个状态通道打包成2字节

**每采样点字节数**：
```
bytes = 8 + 2×模拟通道数 + 2×ceil(状态通道数/16)
```

**状态量打包示例**（6个状态：0,0,0,0,1,1）：
```
二进制：110000（靠前通道=低位）
扩展：0000000000110000
十六进制：0030
存储：3000（小端序）
```

### Binary32 / Float32 格式

模拟量用4字节存储：
- Binary32：有符号32位整数
- Float32：IEEE 754单精度浮点数

---

## 时间计算

```
绝对时间 = CFG首点时间 + (timestamp × time_mult)
```

- timestamp单位：CFG文件中定义（微秒或纳秒）
- time_mult：时标倍率因子

---

## HDR 厂家格式

> 注意：HDR非COMTRADE标准格式，各厂家自定义XML结构

### 标准结构

```xml
<FaultReport>
  <!-- 故障开始时间（用于时间同步） -->
  <FaultStartTime>2024-06-28 16:33:20:213</FaultStartTime>

  <!-- 装置信息 -->
  <DeviceInfo>
    <name>厂站名称</name>
    <value>xxxx</value>
  </DeviceInfo>
  <DeviceInfo>
    <name>装置型号</name>
    <value>PCS-931A</value>
  </DeviceInfo>
  <!-- ... 更多DeviceInfo ... -->

  <!-- 保护动作事件 -->
  <TripInfo>
    <time>0015ms</time>
    <name>纵联差动保护动作</name>
    <phase>ABC</phase>
    <value>1</value>    <!-- 1=动作, 0=返回 -->
  </TripInfo>

  <!-- 故障参数（可能内嵌在TripInfo中） -->
  <FaultInfo>
    <time>0000ms</time>
    <name>故障相电压</name>
    <value>28.20</value>
    <unit>V</unit>
  </FaultInfo>

  <!-- 状态量信息 -->
  <DigitalStatus>
    <name>保护启动</name>
    <value>1</value>
  </DigitalStatus>

  <!-- 开关量变位事件 -->
  <DigitalEvent>
    <time>0091ms</time>
    <name>A相跳闸出口</name>
    <value>1</value>
  </DigitalEvent>

  <!-- 定值信息（部分厂家） -->
  <SettingValue>
    <name>CT一次额定值</name>
    <value>4000</value>
    <unit>A</unit>
  </SettingValue>

  <!-- 数据文件信息 -->
  <DataFileSize>88896</DataFileSize>
  <FaultKeepingTime>7055ms</FaultKeepingTime>
</FaultReport>
```

### 常见模块

| 模块 | 说明 | 字段 |
|------|------|------|
| `FaultStartTime` | 故障绝对时间 | 时间戳 |
| `DeviceInfo` | 装置信息 | name, value |
| `TripInfo` | 保护动作事件 | time, name, phase, value |
| `FaultInfo` | 故障参数 | time, name, value, unit |
| `DigitalStatus` | 状态量（当前状态） | name, value |
| `DigitalEvent` | 开关量变位事件 | time, name, value |
| `SettingValue` | 保护定值 | name, value, unit |
| `RelayEnaValue` | 软压板状态 | name, value |
| `DataFileSize` | 数据文件大小 | 字节数 |
| `FaultKeepingTime` | 故障保持时间 | 毫秒 |

### 厂家差异

| 厂家 | 特殊模块 | 编码 |
|------|----------|------|
| 南瑞继保 PCS | DigitalStatus, DigitalEvent | GB18030 |
| 南瑞继保 CSC | DeviceInfo, TripInfo | GB18030 |
| 长园深瑞 PRS | RelayEnaValue, SettingValue | UTF-8 |
| 四方 CSC | DeviceInfo, TripInfo | GB18030 |
| 许继 WZH | - | GB18030 |

---

## 与1999版差异

| 项目 | 1999版 | 2013版 |
|------|--------|--------|
| 单文件格式 | 不支持 | .CFF格式 |
| 数据类型 | ASCII, Binary16 | 新增Binary32, Float32 |
| CFG版本标识 | 无 | 必选rev_year |
| 时间精度 | 微秒 | 支持纳秒 |
| 编码 | ASCII | 支持UTF-8 |
| CFG时间信息 | 可选 | 必选 |

---

## 参考资料

- IEEE C37.111-1999/2013
- IEC 60255-24:2013
- IEEE 754-2008 浮点数标准
