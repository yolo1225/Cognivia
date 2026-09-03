# 智能制造实训完整知识包 (smart_manufacturing)

本文件用于智能制造提交夹具的空库导入演示，请与启动夹具二选一使用。

## 工业互联网网络体系
- **knowledge_id:** `ki_00040ffb65674150`
- **category:** 网络体系
- **difficulty:** 2
- **tags:** network, factory-inner, factory-outer, connectivity, source_record:ii_网络体系_001
- **source:** [工业互联网产业联盟《工业互联网体系架构2.0》（2020）](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业互联网网络体系分为工厂内网络与工厂外网络两部分。工厂内网络连接车间内的设备、控制器与信息系统，实现设备互联与数据采集，强调实时性与确定性；工厂外网络连接企业、供应链与用户，支撑远程协同与云服务，强调覆盖与安全。网络体系是工业互联网的数据采集与传输基础，其建设需要统筹有线与无线、内网与外网的协同，实现人、机、物的全面互联。工厂内网与工厂外网的边界划分与协同是工业互联网网络规划的关键。

## PLC 定义与循环扫描工作原理
- **knowledge_id:** `ki_07efe4e93e4a7f74`
- **category:** PLC基础
- **difficulty:** 1
- **tags:** plc, scan-cycle, definition, control, source_record:plc_PLC基础_001
- **source:** [IEC 61131 可编程控制器标准](https://www.iec.ch)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

PLC（可编程逻辑控制器）是专为工业环境设计的数字运算电子系统，通过可编程存储器执行逻辑运算、顺序控制、定时、计数与算术运算等指令，经输入输出接口控制各类机械设备与生产过程。PLC 的核心工作方式是循环扫描：在一个扫描周期内依次完成读取输入、执行用户程序、更新输出三个阶段，周而复始。扫描周期决定了控制系统的响应速度，输入信号只有在读取阶段被采集、输出信号在执行后统一刷新，因此理解扫描机制是正确编写 PLC 程序与排查时序问题的前提。

## PLM 产品生命周期管理
- **knowledge_id:** `ki_19881678b556ae7d`
- **category:** 数字化设计
- **difficulty:** 2
- **tags:** plm, bom, lifecycle, configuration, source_record:im_数字化设计_005
- **source:** [ISO 10303 (STEP) 产品数据交换标准系列](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

PLM（产品生命周期管理）是对产品从需求、设计、制造、销售到服务、报废全生命周期内相关数据与过程进行统一管理的技术与方法。它以产品的单一数据源（如三维模型、BOM）为核心，管理版本、变更、配置与审批流程，使跨部门、跨地域的团队围绕一致的产品信息协同工作。PLM 的关键价值在于打通设计、工艺、制造、售后各环节的数据断层，保证信息一致与可追溯，支持并行工程与变更的受控传播。实践中 PLM 常与 ERP、CAD、MES 集成，形成从研发到制造再到服务的信息主线。实施 PLM 应重视流程再造与数据治理，避免只上系统而不梳理业务规则。

## 机器人安全概述
- **knowledge_id:** `ki_1a479143e7e4a51c`
- **category:** 安全
- **difficulty:** 2
- **tags:** safety, risk-assessment, iso10218, hazard, source_record:robot_安全_001
- **source:** [ISO 10218 工业机器人安全要求](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业机器人具有高速、大力矩运动特性，可能造成挤压、碰撞等伤害，因此安全是机器人应用的首要问题。机器人安全遵循 ISO 10218 标准，核心原则是通过风险分析与风险评估识别危险，再采取消除、防护或警示等措施控制风险。安全措施通常包括：安全围栏隔离、安全门联锁、急停装置、光幕或激光扫描器防护、限速控制等。机器人作业区与人员活动区应有效隔离，进入防护区域需停机。安全是所有机器人操作与集成的前提，任何作业都应在安全措施到位后进行。

操作步骤：
1. 在操作或集成前进行风险分析与风险评估，识别挤压、碰撞等危险。
2. 根据风险选择消除、防护或警示等控制措施。
3. 核对安全围栏、安全门联锁、急停装置、光幕或激光扫描器及限速控制等措施是否适用。
4. 确保机器人作业区与人员活动区有效隔离；进入防护区域前执行停机要求。

预期结果：
作业开始前已识别主要风险，并落实与风险相匹配的隔离、防护或警示措施。

常见错误：
未完成风险分析、未采取有效隔离，或在安全措施不到位时进入作业区，都会增加挤压和碰撞伤害风险。

适用范围：
适用于工业机器人操作与集成前的通用安全准备；具体风险控制应遵循适用标准、现场规范和设备制造商要求。

## TIA Portal 软件概述
- **knowledge_id:** `ki_1fab2a5c6c5ad504`
- **category:** TIA Portal实操
- **difficulty:** 1
- **tags:** tia-portal, siemens, engineering, ide, source_record:plc_TIA实操_001
- **source:** [西门子 TIA Portal 官方文档](https://support.industry.siemens.com)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

TIA Portal（全集成自动化门户）是西门子统一的工程组态平台，集成 PLC 编程、HMI 画面组态、驱动调试与网络配置等功能，用于西门子 S7-1200/1500 等控制器的工程开发。TIA Portal 采用项目化、图形化的集成开发环境，在一个项目中完成硬件组态、程序编写、监控调试与诊断。其统一的工程环境简化了 PLC 与 HMI、驱动之间的集成，提高了工程开发效率。学习 TIA Portal 是掌握西门子 PLC 应用的关键，核心包括项目视图、设备组态、程序编辑器与在线工具。

## 项目创建与硬件组态
- **knowledge_id:** `ki_1fe7f407915d15fb`
- **category:** TIA Portal实操
- **difficulty:** 2
- **tags:** project, hardware-configuration, device, io, source_record:plc_TIA实操_002
- **source:** [西门子 TIA Portal 官方文档](https://support.industry.siemens.com)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

在 TIA Portal 中进行 PLC 工程开发，首先创建项目并添加 PLC 设备，然后进行硬件组态。硬件组态包括配置 CPU 型号与版本、添加信号模块与通信模块、设置 I/O 地址与参数、配置网络接口等。组态需与实际硬件一致，CPU 型号、模块类型与插槽位置必须匹配，否则无法正确下载与运行。组态完成后，组态的变量与地址才能在程序中使用。硬件组态是 PLC 工程的基础环节，其准确性直接影响程序的正确执行与后续调试。

操作步骤：
1. 创建工程并添加与实际控制器一致的 PLC 设备。
2. 按实际 CPU 型号和版本配置设备，并补充所使用的信号模块与通信模块。
3. 核对模块类型和插槽位置，设置 I/O 地址、模块参数和网络接口。
4. 完成组态后，再在程序中使用已组态的变量与地址。

预期结果：
工程中的变量和地址可用于后续程序；CPU、模块和插槽信息与实际硬件保持一致。

常见错误：
CPU 型号、模块类型或插槽位置与实际硬件不一致，会导致程序无法正确下载或运行。

适用范围：
适用于 TIA Portal 中的 PLC 工程组态；具体 CPU、模块和版本以现场硬件及来源文档为准。

## 机器人 I/O 信号
- **knowledge_id:** `ki_209aa3438fb46c68`
- **category:** IO与执行器
- **difficulty:** 2
- **tags:** io, signal, digital-input, digital-output, source_record:robot_IO与执行器_001
- **source:** [FANUC 机器人编程指南（I/O 编程）](https://www.iso.org)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

机器人的 I/O 信号用于机器人与外部设备（夹具、输送线、传感器、PLC）之间的交互。数字量输入（DI）接收外部信号，如工件到位、夹紧完成、安全门状态；数字量输出（DO）控制外部设备，如夹爪开合、启动输送线、输出完成信号。I/O 信号通过机器人的 I/O 模块或通信接口（如 EtherNet/IP、PROFINET）与外部设备连接。程序中通过等待输入信号、置位输出信号实现与外部设备的协同控制。正确配置与使用 I/O 是实现机器人自动化单元联动的关键。

## OPC UA 统一通信架构
- **knowledge_id:** `ki_213f5f85ca840f54`
- **category:** 工业物联网
- **difficulty:** 3
- **tags:** opc-ua, iec62541, interoperability, information-model, source_record:im_工业物联网_006
- **source:** [IEC 62541 (OPC UA) 统一通信架构](https://opcfoundation.org)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

OPC UA（开放平台通信统一架构，IEC 62541）是面向工业自动化与信息集成的平台无关通信标准，提供安全、可靠、可扩展的数据交换机制。它定义了一套统一的信息模型，使来自不同厂商、不同层级的设备与系统能够以语义一致的方式描述与交换数据，解决传统 OPC 绑定 Windows 平台与缺乏安全机制的局限。OPC UA 支持客户端/服务器与发布/订阅两种通信模式，内置加密、认证与授权等安全机制，可贯穿传感器、PLC 到 MES、云端各层。它是工业互联网与智能制造实现跨系统互操作的关键技术。实践中应基于统一信息模型规范建模，避免各系统各定义一套语义导致集成困难。

## 机器人与外设协同
- **knowledge_id:** `ki_22ac9040e58bb0e2`
- **category:** IO与执行器
- **difficulty:** 3
- **tags:** integration, plc, conveyor, interlock, source_record:robot_IO与执行器_003
- **source:** [《工业机器人应用技术（第二版）》（蒋正炎等，高等教育出版社）](https://www.iso.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业机器人通常作为自动化单元的一部分，与 PLC、输送线、定位工装、视觉系统等外设协同工作。协同通过 I/O 信号或工业总线实现：PLC 负责整体流程调度，机器人执行具体作业，二者通过信号握手（如请求、到位、完成）实现配合。典型的协同流程如：输送线把工件送到定位工装，到位信号触发机器人抓取，机器人完成作业后输出完成信号，PLC 控制输送线放行。设计协同逻辑时需确保信号联锁完备、时序清晰、异常处理得当，避免冲突与误动作。

操作步骤：
1. 明确 PLC、机器人、输送线、定位工装和视觉等外设的职责。
2. 为协同过程定义请求、到位和完成等 I/O 或工业总线信号。
3. 按工件到位、触发抓取、机器人完成、输送线放行的顺序核对信号握手。
4. 检查信号联锁和时序是否完整，并为异常情况保留处理边界。

预期结果：
PLC 可按整体流程调度外设，机器人完成具体作业，双方通过约定信号完成协同。

常见错误：
信号联锁不完整、时序不清晰或异常处理不足，可能导致协同冲突和误动作。

适用范围：
适用于机器人与 PLC 及自动化外设协同的通用逻辑；实际信号地址和时序以现场控制方案为准。

## 预测性维护
- **knowledge_id:** `ki_260b8a37072e8657`
- **category:** 工业智能
- **difficulty:** 3
- **tags:** predictive-maintenance, condition-monitoring, rul, fault-prediction, source_record:im_工业智能_002
- **source:** [工业互联网产业联盟《工业智能白皮书（2022）》](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

预测性维护通过持续监测设备状态数据（振动、温度、电流等），结合机理模型或机器学习模型预测设备故障的发生时间与失效模式，从而在故障发生前安排维护，避免非计划停机。它区别于事后维护（坏了再修）与定期预防性维护（按固定周期），追求在降低维护成本的同时保障设备可用性。典型实现包括状态监测、特征提取、异常检测、剩余寿命预测与维护决策优化等环节。预测性维护的关键挑战在于故障样本稀缺、工况多变与模型泛化，通常需将机理知识与数据驱动方法结合。实践中应优先选择关键设备与高频失效模式切入，持续积累故障标注数据并迭代模型，量化评估其经济收益。

## CAD 计算机辅助设计
- **knowledge_id:** `ki_283a736369af182f`
- **category:** 数字化设计
- **difficulty:** 1
- **tags:** cad, parametric-modeling, step, digital-design, source_record:im_数字化设计_001
- **source:** [ISO 10303 (STEP) 产品模型数据交换标准](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

CAD（计算机辅助设计）利用计算机系统辅助完成产品的几何建模、工程制图与设计表达，是数字化设计的起点。现代 CAD 已从二维绘图发展为三维参数化建模，通过尺寸约束、特征建模和装配关系构建完整的产品数字模型，支撑设计复用、干涉检查与后续分析制造环节的数据传递。参数化建模使修改一处尺寸即可自动更新相关几何，显著提升设计变更效率。CAD 模型是数字化设计制造的单一数据源，其准确性直接影响 CAE、CAM、CAPP 等下游环节。实践中应规范建模命名、图层与单位等约定，采用统一的模型数据格式以便跨系统交换，典型的产品数据交换标准为 STEP（ISO 10303）。

## 示教器操作
- **knowledge_id:** `ki_2e34400aa000b493`
- **category:** 示教编程
- **difficulty:** 2
- **tags:** teach-pendant, jog, manual-mode, navigation, source_record:robot_示教编程_001
- **source:** [ISO 10218-1 工业机器人安全要求（示教控制装置条款）](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

示教器（示教盒）是操作与编程工业机器人的手持装置，集成了显示器、按键与使能开关。通过示教器可实现机器人手动移动（点动）、坐标切换、程序编辑、参数设置与运行监控。手动移动是示教的基础，可在关节坐标或直角坐标下对各轴进行点动，也可切换不同坐标系以直观地移动机器人。示教器操作通常需配合使能开关（三位使能装置），只有正确按压使能开关才能上使能移动机器人。熟练掌握示教器的菜单结构与手动操作是安全、高效编程的前提。

操作步骤：
1. 通过示教器进入手动操作，选择关节坐标或直角坐标方式。
2. 根据操作目标切换坐标系，并以点动方式移动相应轴。
3. 按示教器的使能开关要求完成上使能后再进行移动操作。
4. 使用示教器查看程序、参数和运行监控信息。

预期结果：
操作者能够在选定坐标方式下完成手动点动，并通过示教器查看相关操作信息。

常见错误：
未按使能开关要求上使能时不应尝试移动机器人；不理解坐标方式或菜单结构会增加误操作风险。

适用范围：
适用于带示教器和使能装置的工业机器人；具体按钮、坐标名称和安全步骤以设备制造商手册为准。

## 置位与复位指令
- **knowledge_id:** `ki_310e5b610c687f24`
- **category:** 梯形图编程
- **difficulty:** 1
- **tags:** set, reset, s, r, latch, source_record:plc_梯形图编程_003
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

置位（S）与复位（R）指令用于将指定位设置为 1 或 0，并保持该状态，是实现自锁与记忆功能的常用手段。与普通线圈输出不同，置位后的位在置位条件消失后仍保持为 1，直到被复位指令清零。典型应用如：启动按钮置位电机运行标志、停止按钮复位该标志，实现启保停控制。使用置位复位时需注意程序中对同一位的置位与复位逻辑要清晰，避免多处置位复位导致状态不确定；对于安全相关信号，还应结合硬件联锁保证安全。

## IEC 61131-3 五种编程语言
- **knowledge_id:** `ki_34b6c891863fe3f7`
- **category:** PLC基础
- **difficulty:** 2
- **tags:** iec61131-3, ld, fbd, sfc, st, il, source_record:plc_PLC基础_003
- **source:** [IEC 61131-3 可编程控制器编程语言](https://www.iec.ch)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

IEC 61131-3 是可编程控制器编程语言的国际标准，定义了五种语言：梯形图（LD）、功能块图（FBD）、顺序功能图（SFC）、指令表（IL）与结构化文本（ST）。梯形图类似继电器电路，直观易读，适合逻辑控制，是最常用的图形化语言；功能块图以图形化功能块表示逻辑关系；顺序功能图适合描述顺序流程；结构化文本类似高级语言，适合复杂算法与数据处理；指令表为助记符文本形式。标准还统一了程序组织单元与数据类型。采用标准化语言可提升程序的可移植性与可维护性，使不同厂商 PLC 的编程模型趋于统一。

## UR ROS 2 Driver 安装与实时通信边界
- **knowledge_id:** `ki_3631ce09e52555f7`
- **category:** 机器人仿真与集成
- **difficulty:** 3
- **tags:** universal-robots, ros2, driver, network, realtime, public_source_commit:f6cae596ae0ba7a5045a89b1e847c47155d7e203
- **source:** [Universal Robots ROS 2 Driver installation (commit f6cae59)](https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/installation/installation.rst)
- **license:** BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30; source_blob_sha=0ba605065d3d22f3dbf6955a1edea1b6e6d99983
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

Universal Robots ROS 2 Driver 提供 CB3 与 e-Series 机器人的 ROS 2 集成。官方文档建议优先使用二进制包；当前 main 分支对应 ROS 2 Rolling，其他 ROS 2 发行版应使用相应分支。机器人控制对周期时间有要求，官方建议使用低延迟或 PREEMPT_RT 内核，并在 ROS PC 与机器人控制器之间使用直连网络而非交换机。

操作步骤：
1. 确认 ROS 2 发行版与 Driver 分支对应；main 分支仅按来源文档支持 ROS 2 Rolling。
2. 安装 ROS 2 后，优先安装 `ros-${ROS_DISTRO}-ur` 二进制包；仅在需要开发或修改时从源代码构建。
3. 为控制任务准备低延迟或 PREEMPT_RT 内核，并使用 ROS PC 到机器人控制器的直连网络。
4. 若从源码构建，先创建 colcon 工作区、导入来源仓库指定依赖、安装依赖并编译工作区。

预期结果：
ROS 2 环境中可获得 UR Driver；控制任务具有与来源文档一致的版本、网络和周期时间准备条件。

常见错误：
ROS 2 发行版与分支不对应，或连续拉取后上游依赖版本发生变化，可能导致构建失败；不可靠的网络连接不适合直接用于严格周期的机器人控制。

适用范围：
适用于 Universal Robots ROS 2 Driver 的 CB3、e-Series 与仿真接入；实际机器人控制还必须遵循设备安全手册。

## 功能 FC 与功能块 FB
- **knowledge_id:** `ki_3b59eadd9e7bc4e2`
- **category:** 程序结构
- **difficulty:** 3
- **tags:** fc, fb, function, function-block, encapsulation, source_record:plc_程序结构_002
- **source:** [IEC 61131-3 可编程控制器编程语言](https://www.iec.ch)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

功能（FC）与功能块（FB）是 PLC 程序模块化的核心机制，用于封装可复用的逻辑。FC 无内部存储，每次调用不保留上次状态，适合纯逻辑运算；FB 带背景数据块，调用时保留内部变量的状态，适合封装电机控制、阀门控制等需要记忆状态的对象。将重复的控制逻辑封装为 FC/FB，可减少代码重复、提高可维护性，是面向对象思想在 PLC 编程中的体现。设计时应明确接口参数，采用参数化而非硬编码，使同一个 FB 可实例化多个对象（如多台相同的电机）。

## 轨迹规划基础
- **knowledge_id:** `ki_3bebafdc01501051`
- **category:** 示教编程
- **difficulty:** 3
- **tags:** trajectory-planning, acceleration, smoothing, transition, source_record:robot_示教编程_007
- **source:** [《工业机器人应用技术（第二版）》（蒋正炎等，高等教育出版社）](https://www.iso.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

轨迹规划指机器人按预定路径、速度与加速度运动的过程。机器人运动需经过加速、匀速、减速阶段，轨迹规划的平滑程度影响运动平稳性与节拍。点与点之间的过渡（转角）可通过过渡半径或连续路径控制，使运动平滑衔接，减少停顿与冲击。合理的轨迹规划需平衡速度、精度与平滑性：速度过快可能产生振动与超调，影响精度；过度平滑可能降低效率。理解加减速与过渡原理，是优化机器人运动质量、延长设备寿命的关键。

## CAM 计算机辅助制造
- **knowledge_id:** `ki_448fb4aafa9eb2d8`
- **category:** 数字化设计
- **difficulty:** 2
- **tags:** cam, nc-programming, toolpath, step-nc, source_record:im_数字化设计_003
- **source:** [ISO 14649 (STEP-NC) 数控数据模型](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

CAM（计算机辅助制造）根据 CAD 生成的产品模型与工艺要求，自动编制数控加工程序并驱动机床加工。CAM 系统将刀具路径规划、切削参数设置、后置处理等环节自动化，生成适配特定机床与数控系统的加工程序。其核心在于把设计几何转换为可执行的加工轨迹，同时考虑刀具半径补偿、进给速度、主轴转速与加工余量等因素，以保证加工质量与效率。CAM 与 CAD 集成后，设计变更可直接传导至加工代码更新。CAM 数据交换的代表标准为 STEP-NC（ISO 14649），它把几何与工艺信息统一描述。实践中需针对不同机床进行后置处理配置，并通过仿真校验刀轨、防止碰撞与过切，经试切验证后再批量投产。

## 智能制造的定义与内涵
- **knowledge_id:** `ki_4603d844f705d61b`
- **category:** 总览与体系
- **difficulty:** 1
- **tags:** intelligent-manufacturing, definition, integration, source_record:im_总览与体系_001
- **source:** [工信部等八部门《“十四五”智能制造发展规划》（2021）](https://www.miit.gov.cn)
- **license:** 政府公开文件; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

智能制造是基于新一代信息通信技术与先进制造技术深度融合，贯穿设计、生产、管理、服务等制造活动各环节，具有自感知、自学习、自决策、自执行、自适应等功能的新型生产方式。其本质不是简单地用自动化设备替代人工，而是通过数据驱动实现制造系统的全流程优化与协同。智能制造以智能工厂为载体、以关键制造环节智能化为核心、以端到端数据流为基础、以网通互联为支撑，目标是在保证质量的前提下降低制造成本、缩短交付周期、提升对个性化需求的响应能力。理解智能制造应把握数字化、网络化、智能化三个递进层次，其中数字化是基础、网络化是纽带、智能化是方向。

## OpenPLC Runtime v4 容器化部署与编辑器连接
- **knowledge_id:** `ki_52b92f4c531b92d9`
- **category:** PLC 仿真与集成
- **difficulty:** 3
- **tags:** openplc, runtime, docker, iec-61131-3, simulation, public_source_commit:bf82b1b661fd95c9899969f629d692b77b4e1454
- **source:** [OpenPLC Runtime v4 README (commit bf82b1b)](https://github.com/Autonomy-Logic/openplc-runtime/blob/bf82b1b661fd95c9899969f629d692b77b4e1454/README.md)
- **license:** MIT License; public repository; captured 2026-08-30; source_blob_sha=b90f2ab9a4c5774f343309036514754dcbc02463
- **ability_weights:** `{"theory":0.2,"practice":0.5,"problem_solving":0.2,"knowledge_breadth":0.1,"learning_speed":0.0}`

OpenPLC Runtime v4 是可在标准计算硬件上运行 IEC 61131-3 程序的无界面 PLC Runtime。它通过 HTTPS REST API 与 OpenPLC Editor v4 连接；Editor 可上传程序、监视编译过程并控制执行。Runtime 的默认服务端口为 8443，运行时本身不提供浏览器管理界面。

操作步骤：
1. 拉取公开镜像 `ghcr.io/autonomy-logic/openplc-runtime:latest`。
2. 使用来源文档给出的 Docker 命令映射 8443 端口，并挂载运行时数据卷。
3. 启动后在 OpenPLC Editor v4 中配置 Runtime 的 IP 地址和凭据，而不是在浏览器中直接打开 8443 端口。
4. 在 Editor 中完成程序设计、编译、上传，并通过 Editor 控制 PLC 执行和变量调试。

预期结果：
Runtime 监听 8443 端口，Editor 可通过 HTTPS 与其连接、上传程序并监视编译和执行状态。

常见错误：
Runtime v4 没有 v3 的浏览器界面，直接在浏览器打开 `https://localhost:8443` 不是正确的管理方式；连接失败时应先核对 Runtime 地址、凭据和端口映射。

适用范围：
适用于 OpenPLC Runtime v4 与 OpenPLC Editor v4 的软件仿真或集成环境；容器权限、网络暴露和实际 I/O 接入必须按部署环境的安全要求配置。

## 工业互联网标识解析体系概述
- **knowledge_id:** `ki_5859dd9ae17dbc6d`
- **category:** 标识解析
- **difficulty:** 2
- **tags:** identification, resolution, infrastructure, traceability, source_record:ii_标识解析_001
- **source:** [工信部《工业互联网标识管理办法》（2021）](https://www.miit.gov.cn)
- **license:** 政府公开文件; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业互联网标识解析体系是工业互联网新型基础设施的重要组成部分，由标识编码与标识解析两部分构成，类似互联网的域名系统。通过统一融合的标识解析体系，企业可访问产品在设计、生产、物流、销售、使用等各环节的信息，实现供应链精准对接、产品全生命周期管理与智能化服务。我国已建成北京、上海、广州、武汉、重庆五大国家顶级节点及南京、贵阳两个灾备节点，形成5+2顶层架构，并实现 VAA、Handle、OID、Ecode、GS1、MA 等多种标识体系的互联互通。

## 比较指令
- **knowledge_id:** `ki_5b9572b29e6bbe6e`
- **category:** 梯形图编程
- **difficulty:** 2
- **tags:** comparison, equal, greater-than, range, source_record:plc_梯形图编程_007
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

比较指令用于比较两个操作数的大小关系，结果作为逻辑条件参与控制。常见比较类型包括等于、不等于、大于、大于等于、小于、小于等于，以及判断数值是否落在指定区间的范围内比较。比较指令可作用于整数、实数、时间、字符串等多种数据类型。典型应用如：根据温度、压力等模拟量值是否超限触发报警，根据计数结果判断工序切换，根据产品编号分拣等。使用比较指令时需注意比较双方的数据类型一致，浮点数比较应避免直接判断相等（因精度误差），宜采用区间比较。

## 计数器指令
- **knowledge_id:** `ki_5c03786f12f901c9`
- **category:** 梯形图编程
- **difficulty:** 2
- **tags:** counter, ctu, ctd, ctud, counting, source_record:plc_梯形图编程_006
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

计数器指令用于对事件进行计数，S7-1200 的 IEC 计数器数量仅受存储器容量限制，以背景数据块标识。主要类型包括：加计数器（CTU），计数输入端 CU 出现上升沿时计数值 CV 加 1，达到预设值 PV 时输出 Q 为 1，复位端 R 清零；减计数器（CTD），CD 上升沿时 CV 减 1，减到 0 时 Q 为 1，装载端 LD 将 CV 置为 PV；加减计数器（CTUD），可同时加计数与减计数。计数值的数据类型可为 SINT、INT、DINT 等。计数器常用于产品计数、工位计数、循环次数控制等场景。高速计数需求应使用高速计数器（HSC），普通计数器受扫描周期限制。

## 在线示教编程
- **knowledge_id:** `ki_60615564b22f71ce`
- **category:** 示教编程
- **difficulty:** 2
- **tags:** teaching, online-programming, point, trajectory, source_record:robot_示教编程_002
- **source:** [《工业机器人应用技术（第二版）》（蒋正炎等，高等教育出版社）](https://www.iso.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

在线示教编程是操作者通过示教器手动引导机器人到达目标位姿并记录示教点，再由控制器按记录的点生成运动轨迹的编程方式。示教时逐点移动到目标位置，记录位置与姿态，并指定点之间的运动类型（关节运动或直线运动）与速度。在线示教简单直观、对操作者编程水平要求低，适合点位少、轨迹简单的任务，但占用生产时间、依赖操作者经验，且精度受示教操作影响。在线示教仍是工业机器人现场最常用的编程方式，是机器人操作的核心技能。

操作步骤：
1. 通过示教器将机器人逐点移动到目标位姿。
2. 记录每个示教点的位置和姿态。
3. 为点与点之间选择关节运动或直线运动，并设置相应速度。
4. 对点位少、轨迹简单的任务，依据记录点生成运动轨迹。

预期结果：
控制器可依据已记录的目标位姿、运动类型和速度形成相应的运动轨迹。

常见错误：
在线示教会占用生产时间，并受操作者经验和示教操作精度影响；不应把它用于超出简单点位、轨迹任务边界的场景。

适用范围：
适用于工业机器人在线示教；具体运动参数、速度限制和试运行要求以设备制造商手册为准。

## 梯形图基本元素与执行顺序
- **knowledge_id:** `ki_617bc7cb95342cd3`
- **category:** 梯形图编程
- **difficulty:** 1
- **tags:** ladder, contact, coil, network, source_record:plc_梯形图编程_001
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

梯形图（LAD）是 PLC 最常用的图形化编程语言，结构与继电器控制电路相似。程序由多个网络（Network）组成，执行顺序为从上到下、从左到右。梯形图的基本元素包括触点（常开、常闭）、线圈、功能块与连接线：触点表示输入条件，线圈表示输出结果，功能块封装定时器、计数器等复杂功能。梯形图的能流（Power Flow）概念对应逻辑的导通，左侧母线视为电源、右侧为输出。掌握梯形图的执行顺序与能流逻辑，是编写正确 PLC 程序的基础。

## 工业传感器与信号采集
- **knowledge_id:** `ki_6710db5cb6eefaed`
- **category:** 工业物联网
- **difficulty:** 1
- **tags:** sensor, signal-acquisition, analog, digital, source_record:im_工业物联网_002
- **source:** [《智能制造技术实训教程》（李彬，化学工业出版社，2025）](http://www.cip.com.cn)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业传感器是感知物理量并将其转换为可测量信号的装置，是智能制造数据采集的源头。按被测对象可分为温度、压力、流量、位移、力、振动、视觉等类型，按输出信号分为开关量（数字量）与模拟量（如 4-20mA 电流、0-10V 电压）。传感器选型需关注量程、精度、响应时间、环境适应性（温度、湿度、防护等级）与输出接口。信号采集需经过信号调理、模数转换（ADC）后接入 PLC 或采集模块。测量精度受传感器本体与信号传输、抗干扰能力共同影响，实践中应做好屏蔽与接地，并定期校准，否则后续的数据分析与智能决策将建立在不可靠的数据之上。

## 网络、平台、安全三大功能体系
- **knowledge_id:** `ki_679055329ed96aed`
- **category:** 总览与体系
- **difficulty:** 1
- **tags:** network, platform, security, functional-system, source_record:ii_总览与体系_003
- **source:** [工业互联网产业联盟《工业互联网体系架构2.0》（2020）](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业互联网功能体系由网络、平台、安全三大部分构成。网络体系负责数据的采集与传输，是实现万物互联的基础；平台体系是核心，负责数据的集成、管理与建模分析，将工业知识与经验沉淀为可复用的模型与服务；安全体系贯穿网络与平台，为数据采集、传输、集成、管理与分析提供全流程保障。三者共同服务于数据这一核心要素：网络采集传输数据，平台处理分析数据，安全保障数据安全。这一结构明确了工业互联网不是单一技术堆叠，而是连接、算力、安全协同的体系。

## 5G+工业互联网
- **knowledge_id:** `ki_6848351a79846659`
- **category:** 网络体系
- **difficulty:** 2
- **tags:** 5g, network-slicing, urllc, private-network, source_record:ii_网络体系_003
- **source:** [工信部《打造“5G+工业互联网”512工程升级版实施方案》](https://www.miit.gov.cn)
- **license:** 政府公开文件; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

5G+工业互联网指将5G通信技术融入工业互联网，利用5G的大带宽、低时延、高可靠与海量连接能力支撑工业场景的无线化与柔性化。5G使工厂内网络摆脱线缆束缚，支撑移动机器人、柔性产线、远程操控等场景，其网络切片技术可为不同业务提供差异化、确定性的网络服务。国家推进5G+工业互联网512工程升级版，加快5G行业虚拟专网建设，强化其网络安全技术手段。5G+工业互联网已成为新型工业化的关键基础设施。

## 边沿检测指令
- **knowledge_id:** `ki_6923d61e529ace1a`
- **category:** 梯形图编程
- **difficulty:** 2
- **tags:** edge-detection, rising-edge, falling-edge, pulse, source_record:plc_梯形图编程_004
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

边沿检测指令用于捕捉信号从 0 到 1（上升沿，P）或从 1 到 0（下降沿，N）的变化瞬间，在一个扫描周期内输出一个脉冲。边沿检测通过比较当前扫描与上一扫描的信号状态实现，因此依赖存储上一周期的状态位。典型应用如：按键单次触发计数、设备到位瞬间锁存数据、故障发生的瞬间记录等，避免因信号持续为 1 而重复触发。使用边沿检测时需注意其依赖扫描周期，对持续时间极短于扫描周期的信号可能漏检，必要时需配合高速输入。

## 末端执行器
- **knowledge_id:** `ki_69f5fe7eec5c477a`
- **category:** IO与执行器
- **difficulty:** 2
- **tags:** end-effector, gripper, tool, tool-center-point, source_record:robot_IO与执行器_002
- **source:** [《工业机器人应用技术（第二版）》（蒋正炎等，高等教育出版社）](https://www.iso.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

末端执行器（末端工具）是安装在机器人手腕末端、直接执行作业的装置，如夹爪、吸盘、焊枪、喷枪等。末端执行器的选择取决于作业类型：搬运装配常用气动夹爪或吸盘，焊接用焊枪，喷涂用喷枪。末端执行器决定了机器人的实际作业能力，其重量计入负载，其尺寸与安装影响可达空间。工具中心点（TCP）是定义在末端执行器上的参考点，机器人运动以 TCP 为基准。正确选择与安装末端执行器，并准确标定 TCP，是机器人作业精度与安全的前提。

## TSN 时间敏感网络
- **knowledge_id:** `ki_6a818aa6404fb1b6`
- **category:** 网络体系
- **difficulty:** 3
- **tags:** tsn, deterministic, clock-sync, low-latency, source_record:ii_网络体系_004
- **source:** [工业互联网产业联盟《工业互联网标准体系3.0》（2021）](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

TSN（时间敏感网络）是在标准以太网基础上扩展的一组标准，提供确定性时延、精准时钟同步与高可靠传输，解决传统以太网在工业实时控制场景下确定性不足的问题。其关键能力包括时间同步、流量调度与冗余传输，目标指标可达端到端确定性时延1~20ms、抖动小于1μs、可靠性99.999%以上。TSN 为 IT 与 OT 的融合提供了统一的确定性网络底座，可与5G协同实现有线无线一体化的确定性传输，支撑运动控制、远程操控等高要求场景。

## 智能制造系统架构
- **knowledge_id:** `ki_713a457ebbd1ce6c`
- **category:** 总览与体系
- **difficulty:** 2
- **tags:** architecture, lifecycle, system-level, reference-model, source_record:im_总览与体系_003
- **source:** [工信部、国家标准委《国家智能制造标准体系建设指南》](https://www.miit.gov.cn)
- **license:** 政府公开文件; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

智能制造系统架构通常由生命周期、系统层级和智能特征三个维度构成，用于描述智能制造系统的组成、层次与能力。生命周期维度涵盖设计、生产、物流、销售、服务等产品全生命周期活动；系统层级维度包括设备层、单元层、车间层、企业层和协同层，从底层的单台设备到跨企业协同逐级递进；智能特征维度按资源要素、互联互通、融合共享、系统集成、新兴业态等能力刻画系统的智能化程度。该三维架构为分析智能制造系统的现状与差距提供了统一框架，帮助企业识别自身所处的位置与提升方向，避免只关注单一设备或单一环节的自动化而忽视系统整体的集成与协同。

## 定时器指令
- **knowledge_id:** `ki_72210960f5fc02c9`
- **category:** 梯形图编程
- **difficulty:** 2
- **tags:** timer, ton, tof, tp, tonr, source_record:plc_梯形图编程_005
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

定时器指令用于实现延时控制，S7-1200 采用符合 IEC 61131-3 的定时器，以背景数据块标识。主要类型包括：接通延时定时器（TON），输入接通后开始计时，到达预设时间 PT 后输出 Q 为 1，输入断开时复位；关断延时定时器（TOF），输入断开后开始计时，延时后输出变 0；脉冲定时器（TP），触发后输出保持固定时长的脉冲；时间累加器（TONR），可累计计时，需复位指令清零。定时器参数包括启动输入 IN、预设时间 PT、当前时间 ET 与输出 Q。TIME 类型以毫秒为单位，最大定时时间约 24 天。使用时应避免用临时变量存储累加时间，需用静态变量以保证跨周期保持。

## URSim 与 UR ROS 2 Driver 联合仿真
- **knowledge_id:** `ki_73040d5c55591199`
- **category:** 机器人仿真与集成
- **difficulty:** 3
- **tags:** universal-robots, ursim, ros2, rviz, simulation, public_source_commit:f6cae596ae0ba7a5045a89b1e847c47155d7e203
- **source:** [Universal Robots ROS 2 Driver simulation (commit f6cae59)](https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/usage/simulation.rst)
- **license:** BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30; source_blob_sha=4a80b5fa5c83c4a70163fddd8ea7428b72fdbe99
- **ability_weights:** `{"theory":0.15,"practice":0.5,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

UR Driver 可与官方 URSim 联合使用；从 Driver 的视角看，URSim 与真实机器人等价。官方文档提供按软件代际区分的 Docker 镜像，并提供 `start_ursim.sh` 统一启动脚本。URSim GUI 通过浏览器访问，Driver 启动后，PolyScope 中的运动会同步到 RViz 可视化。

操作步骤：
1. 使用来源文档的 `ros2 run ur_client_library start_ursim.sh -m <ur_type> -v <ursim_version>` 启动 URSim。
2. 从脚本输出中获取对应软件代际的 URSim GUI 地址，并在浏览器中打开。
3. 使用 `ur_control.launch.py` 启动 Driver，设置 `ur_type` 和 URSim 的 `robot_ip`，并启用 RViz。
4. 在 PolyScope 中移动机器人，观察 RViz 是否同步更新。

预期结果：
URSim GUI 可访问；在 PolyScope 中的机器人运动会同步反映在 RViz 可视化中。

常见错误：
URSim 中的 effort control 虽在部分 PolyScope 版本受支持，但不会产生实际运动；MockSystem 也不支持所有 Driver 功能，不能把这些限制误判为真实机器人故障。

适用范围：
适用于官方 URSim 与 UR ROS 2 Driver 的软件仿真；具体镜像、机器人型号和软件版本以来源文档为准。

## 模拟量标定（工程量转换）
- **knowledge_id:** `ki_735bd6082c73122d`
- **category:** 模拟量处理
- **difficulty:** 3
- **tags:** scaling, engineering-value, normalize, linear, source_record:plc_模拟量处理_002
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

模拟量标定（工程量转换）指把模数转换后的原始数字值转换为具有实际物理意义的工程值。原始数字值（如 0~27648）与工程量（如 0~100℃）通常呈线性关系，可通过线性换算公式或标定指令（如 NORM_X 与 SCALE_X）实现转换。标准做法是先将原始值归一化到 0~1 区间，再按工程量范围线性映射到实际值。标定的准确性依赖输入信号范围与工程量范围的正确配置。标定后的工程值才可用于比较、显示与报警判断，是模拟量应用的核心环节。

## 位逻辑指令
- **knowledge_id:** `ki_73d2c3af2b54aa37`
- **category:** 梯形图编程
- **difficulty:** 1
- **tags:** bit-logic, no, nc, and-or-not, source_record:plc_梯形图编程_002
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

位逻辑指令是 PLC 最基本、最常用的指令，用于对布尔量（位）进行逻辑运算。常开触点（NO）在对应位为 1 时导通，常闭触点（NC）在对应位为 0 时导通；触点串联实现逻辑与（AND），并联实现逻辑或（OR），取反（NOT）实现逻辑非，异或（XOR）判断两信号状态相异。位逻辑指令的典型应用如：启动按钮与停止按钮的联锁、多个安全条件的串联判断等。正确理解触点的常开/常闭与实际输入信号的对应关系（尤其急停等安全信号），是避免逻辑错误的关键。

## UR ROS 2 运动学校准提取与校验
- **knowledge_id:** `ki_753a9cfe0d2d23b1`
- **category:** 机器人仿真与集成
- **difficulty:** 4
- **tags:** universal-robots, ros2, calibration, kinematics, validation, public_source_commit:f6cae596ae0ba7a5045a89b1e847c47155d7e203
- **source:** [Universal Robots ROS 2 Driver robot setup and startup (commit f6cae59)](https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/tree/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc)
- **license:** BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30; source_blob_sha=2c5c1821a7c824362227043eedefa0708fe17ce6, d696c4b2b9b2b35ef91c61df60206d438bd47d8
- **ability_weights:** `{"theory":0.25,"practice":0.4,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

UR 机器人在工厂内完成正、逆运动学校准。官方文档建议将该校准信息提取到 ROS 中使用，否则末端执行器位置可能出现厘米量级偏差。Driver 启动时可通过控制台的校准校验和确认已加载的参数是否与连接机器人匹配。

操作步骤：
1. 确保机器人已上电，即使机器人处于空闲状态也可进行校准提取。
2. 使用来源文档的 `calibration_correction.launch.py`，提供可达的 `robot_ip` 与校准文件的绝对保存路径。
3. 启动 Driver 时将提取的文件作为 `kinematics_params_file` 使用。
4. 检查控制台中的 calibration checksum，确认其与提取文件末行的校验和匹配。

预期结果：
Driver 控制台显示校准已成功检查，且所使用的运动学参数与连接机器人相匹配。

常见错误：
机器人未上电时无法按该流程提取校准；校准参数不匹配时，不能忽略控制台错误并假定末端位置精度正常。

适用范围：
适用于连接真实 UR 机器人的 ROS 2 Driver 运动学校准；URSim 的配置不等同于从实体机器人提取的校准数据。

## 工业机器人定义与分类
- **knowledge_id:** `ki_7ed8333672c0dfbd`
- **category:** 机器人基础
- **difficulty:** 1
- **tags:** industrial-robot, classification, articulated, iso8373, source_record:robot_机器人基础_001
- **source:** [ISO 8373 机器人与机器人装置词汇](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

工业机器人是面向工业领域的多关节机械手或多自由度机器装置，能自动执行工作，靠自身动力与控制能力实现各种功能。按结构形式可分为直角坐标型、SCARA 型、关节型（六轴）、并联型（Delta）等：六轴关节型动作灵活、工作空间大，应用最广；SCARA 适合平面高速装配；并联型适合高速分拣；直角坐标型结构简单、定位精度高。ISO 8373 定义了机器人的相关术语与分类。选型需根据搬运、焊接、装配、喷涂等工艺要求匹配结构形式与负载精度。

## 工业互联网体系架构2.0
- **knowledge_id:** `ki_8aece8fc307b8651`
- **category:** 总览与体系
- **difficulty:** 2
- **tags:** architecture, business-view, functional-view, implementation, source_record:ii_总览与体系_002
- **source:** [工业互联网产业联盟《工业互联网体系架构2.0》（2020）](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

《工业互联网体系架构2.0》从业务视图、功能架构、实施框架三个板块定义工业互联网参考架构。业务视图从业务需求出发梳理应用场景与价值；功能架构定义支撑业务的网络、平台、安全三大功能体系；实施框架则面向行业落地，阐述网络、标识、平台、安全四大要素的实施侧重点与部署方式。该架构继承版本1.0的核心理念，把1.0中的网络、数据、安全三大体系演进为网络、平台、安全，更突出平台对数据的集成、管理与建模分析作用。企业可遵循业务目标—功能要素—实施方式—技术支撑的主线开展建设。

## PLC 硬件组成
- **knowledge_id:** `ki_8e730c3cb5bd0867`
- **category:** PLC基础
- **difficulty:** 1
- **tags:** hardware, cpu, io-module, power-supply, source_record:plc_PLC基础_002
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

PLC 硬件主要由中央处理器（CPU）、电源模块、输入/输出（I/O）模块与通信模块组成。CPU 是核心，负责执行用户程序与逻辑运算，其性能决定扫描速度；电源模块为系统供电；数字量输入模块采集开关、按钮、传感器等开关信号，数字量输出模块驱动继电器、电磁阀、指示灯等执行器；模拟量模块则处理连续变化的温度、压力、电流等信号。PLC 通常采用模块化结构，可按需扩展 I/O 点数。选型时需根据控制点数、响应速度、通信需求与冗余要求综合确定各模块配置。

## 工业网络（现场总线与工业以太网）
- **knowledge_id:** `ki_91b9750c0d2d9f17`
- **category:** 工业物联网
- **difficulty:** 2
- **tags:** fieldbus, industrial-ethernet, profinet, ethercat, source_record:im_工业物联网_005
- **source:** [IEC 61158 / IEC 61784 工业通信网络标准](https://www.iec.ch)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业网络用于连接传感器、执行器、控制器与上位系统，是实现设备互联与数据采集的基础设施，主要包括现场总线与工业以太网两大类。现场总线如 PROFIBUS、CAN、Modbus 等，适合底层设备级通信，具有实时性与抗干扰能力；工业以太网如 PROFINET、EtherCAT、EtherNet/IP 等，在标准以太网基础上增强了实时性与确定性，已成为工业网络的主流方向。选型需综合考虑实时性要求、网络拓扑、传输距离、抗干扰与成本。工业网络设计应合理规划层次（设备层、控制层、信息层）并做好网段隔离与冗余，避免控制网络与办公网络混用带来的性能与安全问题。

## 边缘计算
- **knowledge_id:** `ki_a220d8b8126bb00d`
- **category:** 工业物联网
- **difficulty:** 3
- **tags:** edge-computing, gateway, low-latency, cloud-edge, source_record:im_工业物联网_008
- **source:** [工业互联网产业联盟《工业互联网平台白皮书（2021）》](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

边缘计算指在靠近数据源头的网络边缘侧部署计算与存储能力，就近处理工业现场产生的数据，以减少传输延迟、降低网络带宽压力并保障数据安全。在智能制造中，大量设备数据若全部上传云端会带来高时延与高成本，边缘计算通过在现场网关或边缘节点完成数据预处理、实时控制与本地推理，仅将必要的结果或异常数据上传，实现现场实时处理加云端集中分析的协同。边缘计算与云端的分工取决于业务对时延、带宽与数据量的要求。实践中应根据场景确定哪些计算下沉到边缘，并做好边缘节点的资源管理与安全防护。

## 智能制造能力成熟度模型
- **knowledge_id:** `ki_a78b4a9c7ed554d3`
- **category:** 总览与体系
- **difficulty:** 2
- **tags:** maturity-model, ptrm, capability, gbt39116, source_record:im_总览与体系_004
- **source:** [GB/T 39116-2020《智能制造能力成熟度模型》](https://openstd.samr.gov.cn)
- **license:** 推荐性国家标准; 条文内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

GB/T 39116—2020《智能制造能力成熟度模型》将智能制造能力划分为五个等级，并围绕人员、技术、资源、制造四个核心要素构建评估框架，简称 PTRM 模型。四个要素中，人员要素关注组织、技能与人才保障，技术要素关注数据、集成与信息安全等技术能力，资源要素关注装备、网络等基础资源，制造要素是核心，覆盖设计、生产、物流、销售、服务等制造活动。五个成熟度等级自低向高为规划级、规范级、集成级、优化级、引领级，四个要素下共设 20 个能力子域。该模型用于帮助企业回答如何规划、如何提升、如何评估三个问题，为智能制造能力建设提供统一的度量标尺。

## 工业互联网定义与内涵
- **knowledge_id:** `ki_ac8e095c5488fcb7`
- **category:** 总览与体系
- **difficulty:** 1
- **tags:** industrial-internet, definition, infrastructure, source_record:ii_总览与体系_001
- **source:** [工业互联网产业联盟《工业互联网体系架构2.0》（2020）](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业互联网是新一代信息通信技术与工业经济深度融合的新型基础设施、应用模式和工业生态，通过人、机、物的全面互联，构建起全要素、全产业链、全价值链的新型生产制造和服务体系。其核心是实现工业经济各要素、各环节、各主体的全面连接与数据流通，推动生产方式与企业形态的变革。工业互联网不是单一技术，而是由网络、平台、安全三大体系构成的系统，本质是数据驱动的工业智能化。理解工业互联网应抓住连接、数据、智能的主线：连接是基础，数据是核心，智能是目标。

## 质量管理与 QMS
- **knowledge_id:** `ki_b1213df508e39898`
- **category:** 制造执行
- **difficulty:** 2
- **tags:** qms, quality, iso9000, spc, source_record:im_制造执行_006
- **source:** [ISO 9000 族质量管理体系标准](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

质量管理体系（QMS）通过系统化的过程控制实现产品质量的稳定与持续改进，ISO 9000 族标准是其通用框架，核心思想包括以客户为关注焦点、领导作用、全员参与、过程方法、持续改进、循证决策与关系管理。在智能制造环境下，质量管理从事后检验向过程控制与预防转变，通过在线检测、统计过程控制（SPC）、质量数据分析等手段，实现质量问题的实时发现与闭环改进。QMS 系统负责管理质量文档、检验计划、不合格品处理与纠正预防措施等。实践中的关键是把质量标准落实到工艺参数与检验规则，并保证质量数据可采集、可追溯、可用于分析改进。

## 机器人坐标系
- **knowledge_id:** `ki_bb473cf75ead8132`
- **category:** 机器人基础
- **difficulty:** 2
- **tags:** coordinate-system, joint, cartesian, tool, user, source_record:robot_机器人基础_004
- **source:** [《工业机器人应用技术（第二版）》（蒋正炎等，高等教育出版社）](https://www.iso.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

工业机器人使用多种坐标系描述位置与姿态。关节坐标系以各关节角度表示机器人位姿，是机器人内部的基本表示；直角坐标系（世界坐标系）以机器人基座为原点，用 X、Y、Z 与姿态角描述末端位姿；工具坐标系（TCP）定义在末端执行器上，使编程围绕工具中心点进行，便于沿工具方向运动；用户坐标系由用户在工作场景中自定义，方便沿工件或工装方向编程。正确设置工具坐标系与用户坐标系是高效、准确编程的前提，尤其对离线编程与程序复用至关重要。

## 急停与保护性停止
- **knowledge_id:** `ki_bbbeaa43f0da01bb`
- **category:** 安全
- **difficulty:** 2
- **tags:** emergency-stop, protective-stop, stop-category, safety, source_record:robot_安全_002
- **source:** [ISO 10218-1 工业机器人安全要求（停止功能条款）](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

机器人停止功能分为急停与保护性停止等类型。急停（Emergency Stop）是在紧急情况下由人工触发，立即切断机器人动力，使机器人停止运动，用于防止或减轻伤害；保护性停止（Protective Stop）由安全防护装置（如安全门打开、光幕被遮挡）触发，自动停止机器人运动。安全标准区分不同停止类别（0 类立即断电、1 类受控停止），安全相关控制系统故障时应导致 0 类或 1 类停止。急停与保护性停止必须通过安全相关电路实现，不能仅依赖软件逻辑，且需定期测试确保可靠。

操作步骤：
1. 区分人工触发的急停与由安全防护装置触发的保护性停止。
2. 检查急停和保护性停止是否通过安全相关电路实现，而非仅依赖软件逻辑。
3. 在适用的安全程序中定期测试停止功能的可靠性。
4. 发生安全相关控制系统故障时，按适用的 0 类或 1 类停止要求处理。

预期结果：
能够识别两类停止功能的触发来源，并确认停止功能具备安全相关的实现与测试依据。

常见错误：
把急停与保护性停止混为一谈，或仅依赖普通软件逻辑实现停止功能，会削弱安全控制的可靠性。

适用范围：
适用于工业机器人停止功能的安全要求；停止类别、接线和测试方式必须以适用标准及设备制造商手册为准。

## 模拟量输入输出
- **knowledge_id:** `ki_bdcc4bff0bd0bcd3`
- **category:** 模拟量处理
- **difficulty:** 2
- **tags:** analog, adc, dac, 4-20ma, source_record:plc_模拟量处理_001
- **source:** [《S7-1200 PLC应用教程》（第2版）](https://support.industry.siemens.com)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

模拟量输入输出模块用于处理连续变化的信号，如温度、压力、流量、转速等。模拟量输入模块通过模数转换（ADC）把现场的连续电压或电流信号转换为数字值供 CPU 处理，常见信号制式为 0-10V、0-20mA、4-20mA 等，其中 4-20mA 电流信号因抗干扰能力强、可判断断线（低于 4mA）而应用最广。模拟量输出模块则通过数模转换（DAC）输出连续信号驱动调节阀、变频器等。使用模拟量模块需根据传感器量程配置通道的测量范围与分辨率，并做好屏蔽与接地。

## 机器人主要性能参数
- **knowledge_id:** `ki_c2b42d638cc46952`
- **category:** 机器人基础
- **difficulty:** 1
- **tags:** specification, payload, reach, repeatability, source_record:robot_机器人基础_003
- **source:** [ISO 9283 机器人性能准则及测试方法](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

工业机器人的主要性能参数包括自由度、负载、工作半径、重复定位精度与速度。自由度指机器人独立运动的关节数，常见六轴机器人具有 6 个自由度；负载指机器人末端能承受的最大质量；工作半径指机器人末端可达的最大距离；重复定位精度指机器人多次到达同一目标位姿的一致性，是衡量精度的重要指标，通常可达 ±0.02~±0.1mm；速度决定节拍与生产效率。选型时应根据搬运重量、作业范围、精度要求与节拍需求综合匹配这些参数。

## 机器人程序结构
- **knowledge_id:** `ki_c38752752b340900`
- **category:** 示教编程
- **difficulty:** 2
- **tags:** program-structure, main-program, subroutine, flow, source_record:robot_示教编程_005
- **source:** [FANUC 机器人编程指南（程序结构）](https://www.iso.org)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

机器人程序由主程序与若干子程序组成，主程序控制整体流程，子程序封装特定动作（如抓取、放置、焊接）供主程序调用。程序通常包含初始化、运动指令、I/O 操作、逻辑判断与循环结构。良好的程序结构应模块化、清晰，将重复动作封装为子程序，便于维护与复用。程序还常包含条件分支、循环与等待指令，实现与外部设备（输送线、夹具、传感器）的协同。掌握程序结构是编写可读、可维护机器人程序的基础。

## 运动指令
- **knowledge_id:** `ki_c5760abacfdf0dc5`
- **category:** 示教编程
- **difficulty:** 2
- **tags:** motion-instruction, joint, linear, circular, source_record:robot_示教编程_004
- **source:** [FANUC 机器人编程指南（运动编程）](https://www.iso.org)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

运动指令用于控制机器人末端从当前位置运动到目标位姿，是机器人程序的核心。主要运动类型包括：关节运动（如 MOVJ），各关节同步运动，速度快、路径不保证直线，适合点到点的快速移动；直线运动（如 MOVL），末端沿直线轨迹运动，适合焊接、涂胶等需精确路径的作业；圆弧运动（如 MOVC），末端沿圆弧轨迹运动，适合圆弧焊缝等。运动指令通常还需指定速度、过渡方式与工具、用户坐标系。合理选择运动类型与速度，是保证轨迹精度与节拍平衡的关键。

## ISA-95 企业控制系统集成模型
- **knowledge_id:** `ki_c5a352abd66c1a00`
- **category:** 制造执行
- **difficulty:** 2
- **tags:** isa95, iec62264, hierarchy, integration, source_record:im_制造执行_001
- **source:** [IEC 62264 / ISA-95 企业控制系统集成](https://www.isa.org)
- **license:** 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

ISA-95（对应国际标准 IEC 62264）定义了企业业务系统与制造控制系统之间的接口与信息交换模型，是理解制造企业信息系统分层的经典框架。它将企业信息化分为五个层级：第 0 层为实际生产过程，第 1 层为传感器与执行器，第 2 层为监控与控制系统（如 PLC、SCADA、DCS），第 3 层为制造运营管理（MES 所在层），第 4 层为业务计划与物流（ERP 所在层）。ISA-95 规范了各层之间的数据对象与活动模型，解决 ERP 与 MES、控制系统之间的信息集成问题。该层次模型的价值在于明确各系统职责边界，避免功能重叠与信息孤岛，是 MES 等系统设计与集成的参考依据。

## UR External Control 中断识别与恢复
- **knowledge_id:** `ki_c6e0d437718ca065`
- **category:** 机器人仿真与集成
- **difficulty:** 4
- **tags:** universal-robots, ros2, external-control, recovery, safety, public_source_commit:f6cae596ae0ba7a5045a89b1e847c47155d7e203
- **source:** [Universal Robots ROS 2 Driver startup recovery (commit f6cae59)](https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/usage/startup.rst)
- **license:** BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30; source_blob_sha=d696c4b2b9b2b35ef91c61df60206d438bd47d8
- **ability_weights:** `{"theory":0.2,"practice":0.35,"problem_solving":0.35,"knowledge_breadth":0.1,"learning_speed":0.0}`

当 External Control URCap 程序被中断时，官方文档要求取消暂停或重新启动该程序。中断可能由主动停止程序、保护性停止或急停、外部源未及时发送命令、通过主接口发送其他脚本，或通过示教器执行运动引起。Driver 会报告 reverse interface 连接已断开。

操作步骤：
1. 识别控制台中的 `Connection to reverse interface dropped.` 信息，并确认是否存在程序停止、安全停止、通信中断或其他控制来源。
2. 在本地控制模式下，按来源文档重新运行机器人上的 External Control 程序。
3. 在远程控制模式下，使用来源文档指定的 Dashboard play 调用重新启动程序。
4. 在 headless 模式下，使用来源文档指定的 resend_robot_program 服务重新发送程序。

预期结果：
按当前控制模式恢复 External Control 程序后，Driver 可继续与机器人或仿真对象建立相应的控制连接。

常见错误：
将保护性停止或急停后的恢复当成普通通信重连，会忽略安全状态；发现中断后不先确认触发原因就重复下发程序，可能掩盖真实故障。

适用范围：
适用于 UR ROS 2 Driver 的 External Control 中断恢复；急停和保护性停止后的现场恢复必须优先遵循设备安全程序。

## MES 制造执行系统
- **knowledge_id:** `ki_c98539cffb5cefac`
- **category:** 制造执行
- **difficulty:** 2
- **tags:** mes, manufacturing-execution, traceability, shop-floor, source_record:im_制造执行_003
- **source:** [IEC 62264 / ISA-95 制造运营管理模型](https://www.isa.org)
- **license:** 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

MES（制造执行系统）是位于企业计划层（ERP）与过程控制层之间的制造运营管理系统，负责车间级的生产执行、调度、质量、设备、人员等活动的实时管理。它将 ERP 下达的生产计划分解为可执行的工单与工序任务，采集设备与生产现场数据，实现生产过程的透明化、可追溯与实时调度。MES 的核心功能通常包括工单管理、物料跟踪、质量数据采集、设备状态监控、过程防错与追溯等，遵循 ISA-95 制造运营管理模型。MES 的价值在于打通计划与执行的数据闭环，使计划下达、现场执行、进度反馈及时准确。实施 MES 应以真实业务痛点为导向，与设备和 ERP 充分集成，避免成为孤立的数据录入系统。

## 数字孪生
- **knowledge_id:** `ki_c9a83abb024336c3`
- **category:** 数字化设计
- **difficulty:** 3
- **tags:** digital-twin, simulation, realtime-data, iso23247, source_record:im_数字化设计_006
- **source:** [ISO 23247 数字孪生制造框架](https://www.iso.org)
- **license:** ISO 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

数字孪生通过构建物理实体在数字空间的高保真映射，并借助实时数据与仿真模型实现物理世界与数字世界的双向交互与同步演化。它不是静态的三维模型，而是几何模型、机理或数据模型与实时数据三者融合的产物，能够对物理对象的状态进行监测、诊断、预测与优化。在制造领域，数字孪生可应用于产线仿真、设备预测性维护、工艺优化与远程运维等场景，实现以虚映实、以虚控实。构建数字孪生的关键在于模型精度与实时数据的同步能力，以及仿真模型的可信度验证。实践中应从价值明确的场景切入，逐步积累机理模型与数据，避免追求大而全的展示性孪生而脱离实际业务价值。

## 顺序控制与状态机
- **knowledge_id:** `ki_cb0b853bacd206e7`
- **category:** 程序结构
- **difficulty:** 3
- **tags:** sequential-control, state-machine, step, transition, source_record:plc_程序结构_001
- **source:** [IEC 61131-3 顺序功能图 / 通用程序设计](https://www.iec.ch)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

顺序控制是工业生产中常见的控制方式，把工艺过程划分为若干步（状态），各步之间有明确的转移条件，系统按步骤依次执行。实现顺序控制常用状态机思想，用当前步号（状态变量）记录所处阶段，通过转移条件判断进入下一步。SFC（顺序功能图）语言天然适合描述此类逻辑，也可用梯形图配合步号变量实现。状态机使程序逻辑清晰、易于扩展与调试，广泛用于多工位装配、清洗、包装等流程控制。设计时应确保状态唯一、转移条件完备、并处理异常退出与复位。

## 机器人系统组成
- **knowledge_id:** `ki_cd695947b8909427`
- **category:** 机器人基础
- **difficulty:** 1
- **tags:** system, controller, teach-pendant, manipulator, source_record:robot_机器人基础_002
- **source:** [《工业机器人应用技术（第二版）》（蒋正炎等，高等教育出版社）](https://www.iso.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

工业机器人系统主要由机器人本体（机械手）、控制器、示教器及周边设备组成。本体是执行机构，由基座、手臂、手腕与末端执行器接口构成，通过伺服电机驱动各关节运动；控制器是机器人的大脑，负责运动学计算、轨迹规划、程序执行与 I/O 控制；示教器是人与机器人交互的操作装置，用于手动操作、程序编写与参数设置。此外还常配套安全围栏、末端夹具、视觉系统等周边设备。理解各组成部分的功能是进行机器人操作与维护的基础。

## 工业大数据
- **knowledge_id:** `ki_cf1639cb2c1f44b7`
- **category:** 工业智能
- **difficulty:** 2
- **tags:** industrial-big-data, time-series, data-governance, analytics, source_record:im_工业智能_001
- **source:** [工业互联网产业联盟《工业智能白皮书（2022）》](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业大数据是工业生产过程中产生的海量、多源、高速、高价值密度的数据，涵盖设备运行、工艺参数、质量检测、能耗、生产计划等各类数据。其典型特征包括多模态（结构化、时序、图像）、强时序性与专业关联性，且往往价值密度高但噪声与异常并存。工业大数据的价值在于通过分析挖掘实现质量预测、设备维护、能耗优化与工艺改进等。与传统商业大数据相比，工业数据分析更依赖机理知识与领域经验，纯数据驱动方法在样本不足、工况多变时容易失效。实践中应建立数据采集、清洗、存储与治理体系，将机理模型与数据模型结合，保证数据的完整性与可用性。

## PLC 程序组织单元
- **knowledge_id:** `ki_db57e4a1af87914e`
- **category:** PLC基础
- **difficulty:** 2
- **tags:** ob, fc, fb, db, program-organization, source_record:plc_PLC基础_004
- **source:** [IEC 61131-3 可编程控制器编程语言](https://www.iec.ch)
- **license:** IEC 国际标准; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

PLC 程序按程序组织单元（POU）组织，主要包括组织块（OB）、功能（FC）、功能块（FB）与数据块（DB）。组织块是程序与操作系统的接口，由特定事件触发执行，如主循环 OB1、启动 OB、中断 OB 等；功能（FC）是无内部存储的代码块，多次调用不保留状态；功能块（FB）带独立的背景数据块（DB），调用时保留内部状态，适合封装定时器、计数器等需要记忆的组件；数据块用于存储用户数据。合理划分 POU 是实现程序模块化、可复用与易维护的关键。

## 工业物联网 IIoT
- **knowledge_id:** `ki_dea22bbd80be7245`
- **category:** 工业物联网
- **difficulty:** 1
- **tags:** iiot, industrial-internet, connectivity, sensing, source_record:im_工业物联网_001
- **source:** [工业互联网产业联盟《工业互联网平台白皮书（2021）》](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工业物联网（IIoT）是将传感器、控制器、设备、产品等工业对象通过工业网络互联，实现数据采集、交换与分析的技术体系，是工业互联网的基础。与消费物联网相比，工业物联网更强调高可靠、低时延、实时性与安全性，因为数据直接关联生产过程与设备安全。IIoT 的典型架构包括感知层（传感器与执行器）、网络层（工业网络与网关）与应用层（数据平台与业务应用）。它使原本孤立的设备成为可感知、可连接、可计算的数据源，为数据驱动的生产优化、预测性维护与远程运维提供支撑。实施 IIoT 应重点关注设备联网改造、协议统一与数据治理，避免采集了大量数据却无法转化为业务价值。

## 程序下载与在线监控
- **knowledge_id:** `ki_e0f0e68ceb532784`
- **category:** TIA Portal实操
- **difficulty:** 2
- **tags:** download, online, monitoring, debugging, source_record:plc_TIA实操_003
- **source:** [西门子 TIA Portal 官方文档](https://support.industry.siemens.com)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

程序编写完成后需编译并下载到 PLC 才能运行。下载前应确认程序无编译错误，并选择正确的目标设备与接口。下载后可通过在线监控（Monitor）实时查看变量的值、程序块的执行状态与能流导通情况，是调试的重要手段。在线监控可观察触点通断、定时器计时、数据值变化，配合变量监控表可强制修改变量值进行调试。掌握下载与在线监控是 PLC 调试的基本技能，调试时应遵循先离线检查、再在线验证的流程，避免误操作影响运行中的设备。

操作步骤：
1. 在下载前编译程序并确认不存在编译错误。
2. 选择正确的目标设备和通信接口后下载程序。
3. 下载完成后使用在线监控查看变量值、程序块执行状态和能流导通情况。
4. 结合变量监控表观察触点、定时器和数据值的实际变化；遵循先离线检查、再在线验证的顺序。

预期结果：
可在线观察变量、程序块和能流的运行状态，并据此完成调试验证。

常见错误：
存在编译错误，或选择了错误的目标设备、接口时，不应继续下载；在线调试中的误操作可能影响运行中的设备。

适用范围：
适用于 TIA Portal 的程序下载与在线监控；具体通信连接和设备状态以现场条件为准。

## APS 高级计划与排程
- **knowledge_id:** `ki_e2281032f2474e70`
- **category:** 制造执行
- **difficulty:** 3
- **tags:** aps, scheduling, finite-capacity, optimization, source_record:im_制造执行_005
- **source:** [《智能制造技术概论》（钟波等，机械工业出版社，2025）](http://www.cmpedu.com/books/book/5609442.htm)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

APS（高级计划与排程）基于约束理论、运筹优化与启发式算法，在综合考虑设备产能、物料、人员、工艺、交期等约束条件下，自动生成可行的生产计划与详细排程。与 ERP 的无限产能计划（MRP）不同，APS 采用有限产能逻辑，能够识别瓶颈资源并给出满足交期约束的最优或近似最优排程方案。它通常分为战略层、计划层与排程层，向下与 MES 联动实现计划的动态调整。APS 的核心难点在于模型的准确性与数据质量，产能、节拍、换型时间等基础数据若不准确，排程结果将失去可信度。实践中应先在关键车间试点，持续校准模型，再逐步推广。

## 数字化、网络化、智能化演进路径
- **knowledge_id:** `ki_e2d7953ac404e27a`
- **category:** 总览与体系
- **difficulty:** 1
- **tags:** digitalization, networking, intelligence, evolution, source_record:im_总览与体系_002
- **source:** [工信部等八部门《“十四五”智能制造发展规划》（2021）](https://www.miit.gov.cn)
- **license:** 政府公开文件; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

制造业转型升级遵循数字化、网络化、智能化的演进路径。数字化指将物理世界的产品、设备、工艺、流程转化为可计算、可存储、可传递的数据模型，实现研发设计、生产制造、经营管理等环节的计算机化，是智能制造的基础前提。网络化是在数字化基础上，通过工业互联网、物联网等技术实现设备、系统、企业之间的互联互通与协同，打通信息孤岛，使数据能够在全产业链流动。智能化是最高阶段，系统基于数据通过人工智能、运筹优化等手段进行自学习、自决策、自优化，替代或辅助人工完成复杂分析与决策。三阶段并非严格线性推进，往往并行展开，但应先夯实数字化与网络化基础，避免数据质量差、系统未打通时盲目上智能化应用。

## 工厂内网络与工业以太网
- **knowledge_id:** `ki_e41a07e08282bfe3`
- **category:** 网络体系
- **difficulty:** 2
- **tags:** factory-inner-network, industrial-ethernet, tsn, protocol, source_record:ii_网络体系_002
- **source:** [工业互联网产业联盟《工业互联网体系架构2.0》（2020）](http://www.aii-alliance.org)
- **license:** 公开报告; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

工厂内网络是工业互联网网络体系的底层，连接现场设备、控制器与车间级系统。工厂内网络逐步从传统现场总线向工业以太网演进，如 PROFINET、EtherCAT、TSN 等，以满足高实时、高可靠的数据传输需求。工厂内网络的部署需考虑设备协议多样性（Modbus、OPC UA、各类现场总线）、实时性分级与网段隔离，通常结合边缘网关实现协议转换与数据汇聚。工厂内网络是工业互联网数据采集的基础，其质量直接决定上层平台数据的完整性与实时性。

## 故障诊断与调试
- **knowledge_id:** `ki_e5d3342302e40e27`
- **category:** TIA Portal实操
- **difficulty:** 3
- **tags:** diagnosis, debugging, fault, troubleshooting, source_record:plc_TIA实操_004
- **source:** [西门子 TIA Portal 官方文档](https://support.industry.siemens.com)
- **license:** 厂商官方文档; 内容总结
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

PLC 故障诊断与调试是保证系统稳定运行的重要环节。诊断包括硬件故障（模块异常、通信中断、电源故障）与逻辑故障（程序错误、时序问题、参数设置错误）两类。TIA Portal 提供诊断缓冲区，可查看系统事件、错误与报警信息，帮助定位故障。调试时常用方法包括：观察诊断缓冲区、在线监控程序执行、检查 I/O 指示灯与实际信号、逐段隔离测试逻辑。系统化地排查——先确认硬件与接线、再检查程序逻辑、最后核对参数——能有效缩短故障处理时间。

操作步骤：
1. 查看诊断缓冲区中的系统事件、错误和报警信息。
2. 在线监控程序执行状态，并检查 I/O 指示灯与实际信号。
3. 对逻辑逐段隔离测试，区分硬件、通信、逻辑和参数问题。
4. 按先确认硬件与接线、再检查程序逻辑、最后核对参数的顺序排查。

预期结果：
可依据诊断信息、在线状态和实际信号，将排查聚焦到硬件、逻辑或参数中的相应范围。

常见错误：
模块异常、通信中断、电源故障、程序时序问题或参数设置错误均可能造成异常；不能只检查单一环节就下结论。

适用范围：
适用于 TIA Portal 支持的 PLC 诊断与调试；现场安全处置应遵循设备手册和作业规范。

## 标识解析与产品追溯
- **knowledge_id:** `ki_e9d43cf30b0f3f00`
- **category:** 标识解析
- **difficulty:** 2
- **tags:** traceability, identification, lifecycle, anti-counterfeit, source_record:ii_标识解析_006
- **source:** [工信部《工业互联网标识管理办法》（2021）](https://www.miit.gov.cn)
- **license:** 政府公开文件; 内容总结
- **ability_weights:** `{"theory":0.35,"practice":0.25,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

标识解析体系为产品追溯提供了基础，通过为产品赋予唯一标识并在各环节注册、解析相关信息，实现从原料、生产、物流到销售、使用的全生命周期追溯。消费者或监管方可通过扫码等方式查询产品的来源、批次与流转信息，支撑质量追溯、防伪验证与召回管理。标识解析与区块链等技术结合，可进一步增强追溯信息的可信度与不可篡改性。标识解析是工业互联网实现供应链透明化与全生命周期管理的关键能力。

## UR ROS 2 Driver 启动与控制模式衔接
- **knowledge_id:** `ki_f3c9136c20115ace`
- **category:** 机器人仿真与集成
- **difficulty:** 4
- **tags:** universal-robots, ros2, driver, external-control, controller, public_source_commit:f6cae596ae0ba7a5045a89b1e847c47155d7e203
- **source:** [Universal Robots ROS 2 Driver startup (commit f6cae59)](https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/usage/startup.rst)
- **license:** BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30; source_blob_sha=d696c4b2b9b2b35ef91c61df60206d438bd47d8
- **ability_weights:** `{"theory":0.2,"practice":0.45,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

使用 UR ROS 2 Driver 前，需要完成机器人或 URSim 的准备、External Control URCap 安装及相应程序创建。官方建议通过 `ur_control.launch.py` 启动 Driver；必需参数为 `ur_type` 和 `robot_ip`。启动后 Driver 会启动控制器和辅助节点；单机器人场景下，`blocking_read` 默认开启以让机器人控制循环驱动 ROS 控制节奏。

操作步骤：
1. 确认已完成 Driver 安装、External Control URCap 安装和控制程序创建。
2. 使用 `ros2 launch ur_robot_driver ur_control.launch.py ur_type:=<ur_type> robot_ip:=<robot_ip>` 启动 Driver。
3. 在本地控制模式下加载并运行 External Control 程序；在远程控制模式下使用来源文档列出的 Dashboard 调用加载并启动程序。
4. 使用 `ros2 control list_controllers` 查看已加载控制器；需要时用 `--show-args` 核对启动参数。

预期结果：
Driver、控制器和辅助节点启动，且控制模式中的 External Control 程序与 Driver 运行状态相衔接。

常见错误：
未准备 External Control 程序就启动 Driver，或 `ur_type`、`robot_ip` 与实际对象不匹配，会使控制流程无法正确衔接；通信不可靠时不应关闭默认的 `blocking_read` 后直接假定控制周期正常。

适用范围：
适用于 UR ROS 2 Driver 的真实机器人或 URSim；控制模式与安全操作必须遵循 Universal Robots 的设备文档。
