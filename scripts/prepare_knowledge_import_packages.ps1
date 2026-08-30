[CmdletBinding()]
param(
    [string]$KnowledgeZip = "C:\Users\loyo\Desktop\01_工作项目\2026.6挑战杯\数据集\knowledge.zip",
    [string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) "deliverables\knowledge-import-packages")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Read-ArchiveDataset {
    param(
        [System.IO.Compression.ZipArchive]$Archive,
        [string]$Name
    )

    $entry = $Archive.Entries | Where-Object { $_.FullName -eq $Name } | Select-Object -First 1
    if ($null -eq $entry) {
        throw "知识包缺少数据文件: $Name"
    }
    $reader = [System.IO.StreamReader]::new($entry.Open())
    try {
        return @($reader.ReadToEnd() | ConvertFrom-Json)
    }
    finally {
        $reader.Dispose()
    }
}

function Get-AbilityWeights {
    param([string]$DomainCode, [string]$Category)

    if ($DomainCode -eq "smart_manufacturing") {
        if ($Category -match "PLC|梯形图|TIA|机器人|示教|I/O|模拟量") {
            return [ordered]@{
                theory = 0.20; practice = 0.45; problem_solving = 0.25
                knowledge_breadth = 0.10; learning_speed = 0.0
            }
        }
        return [ordered]@{
            theory = 0.35; practice = 0.25; problem_solving = 0.25
            knowledge_breadth = 0.15; learning_speed = 0.0
        }
    }

    if ($Category -match "Python|数据处理") {
        return [ordered]@{
            theory = 0.25; practice = 0.40; problem_solving = 0.25
            knowledge_breadth = 0.10; learning_speed = 0.0
        }
    }
    return [ordered]@{
        theory = 0.40; practice = 0.20; problem_solving = 0.25
        knowledge_breadth = 0.15; learning_speed = 0.0
    }
}

function Convert-ContentForStructuredMarkdown {
    param([string]$Content, [string]$SourceId)

    # Any Markdown heading would start a new parser section.  Preserve source labels as bold text.
    $normalized = (($Content -replace "`r`n", "`n").Trim() -replace '(?m)^#{1,6}\s+(.+?)\s*$', '**$1**').Trim()
    $appendix = switch ($SourceId) {
        "plc_TIA实操_002" {
@'
### 操作步骤
1. 创建工程并添加与实际控制器一致的 PLC 设备。
2. 按实际 CPU 型号和版本配置设备，并补充所使用的信号模块与通信模块。
3. 核对模块类型和插槽位置，设置 I/O 地址、模块参数和网络接口。
4. 完成组态后，再在程序中使用已组态的变量与地址。

### 预期结果
工程中的变量和地址可用于后续程序；CPU、模块和插槽信息与实际硬件保持一致。

### 常见错误
CPU 型号、模块类型或插槽位置与实际硬件不一致，会导致程序无法正确下载或运行。

### 适用范围
适用于 TIA Portal 中的 PLC 工程组态；具体 CPU、模块和版本以现场硬件及来源文档为准。
'@
        }
        "plc_TIA实操_003" {
@'
### 操作步骤
1. 在下载前编译程序并确认不存在编译错误。
2. 选择正确的目标设备和通信接口后下载程序。
3. 下载完成后使用在线监控查看变量值、程序块执行状态和能流导通情况。
4. 结合变量监控表观察触点、定时器和数据值的实际变化；遵循先离线检查、再在线验证的顺序。

### 预期结果
可在线观察变量、程序块和能流的运行状态，并据此完成调试验证。

### 常见错误
存在编译错误，或选择了错误的目标设备、接口时，不应继续下载；在线调试中的误操作可能影响运行中的设备。

### 适用范围
适用于 TIA Portal 的程序下载与在线监控；具体通信连接和设备状态以现场条件为准。
'@
        }
        "plc_TIA实操_004" {
@'
### 操作步骤
1. 查看诊断缓冲区中的系统事件、错误和报警信息。
2. 在线监控程序执行状态，并检查 I/O 指示灯与实际信号。
3. 对逻辑逐段隔离测试，区分硬件、通信、逻辑和参数问题。
4. 按先确认硬件与接线、再检查程序逻辑、最后核对参数的顺序排查。

### 预期结果
可依据诊断信息、在线状态和实际信号，将排查聚焦到硬件、逻辑或参数中的相应范围。

### 常见错误
模块异常、通信中断、电源故障、程序时序问题或参数设置错误均可能造成异常；不能只检查单一环节就下结论。

### 适用范围
适用于 TIA Portal 支持的 PLC 诊断与调试；现场安全处置应遵循设备手册和作业规范。
'@
        }
        "robot_示教编程_001" {
@'
### 操作步骤
1. 通过示教器进入手动操作，选择关节坐标或直角坐标方式。
2. 根据操作目标切换坐标系，并以点动方式移动相应轴。
3. 按示教器的使能开关要求完成上使能后再进行移动操作。
4. 使用示教器查看程序、参数和运行监控信息。

### 预期结果
操作者能够在选定坐标方式下完成手动点动，并通过示教器查看相关操作信息。

### 常见错误
未按使能开关要求上使能时不应尝试移动机器人；不理解坐标方式或菜单结构会增加误操作风险。

### 适用范围
适用于带示教器和使能装置的工业机器人；具体按钮、坐标名称和安全步骤以设备制造商手册为准。
'@
        }
        "robot_示教编程_002" {
@'
### 操作步骤
1. 通过示教器将机器人逐点移动到目标位姿。
2. 记录每个示教点的位置和姿态。
3. 为点与点之间选择关节运动或直线运动，并设置相应速度。
4. 对点位少、轨迹简单的任务，依据记录点生成运动轨迹。

### 预期结果
控制器可依据已记录的目标位姿、运动类型和速度形成相应的运动轨迹。

### 常见错误
在线示教会占用生产时间，并受操作者经验和示教操作精度影响；不应把它用于超出简单点位、轨迹任务边界的场景。

### 适用范围
适用于工业机器人在线示教；具体运动参数、速度限制和试运行要求以设备制造商手册为准。
'@
        }
        "robot_IO与执行器_003" {
@'
### 操作步骤
1. 明确 PLC、机器人、输送线、定位工装和视觉等外设的职责。
2. 为协同过程定义请求、到位和完成等 I/O 或工业总线信号。
3. 按工件到位、触发抓取、机器人完成、输送线放行的顺序核对信号握手。
4. 检查信号联锁和时序是否完整，并为异常情况保留处理边界。

### 预期结果
PLC 可按整体流程调度外设，机器人完成具体作业，双方通过约定信号完成协同。

### 常见错误
信号联锁不完整、时序不清晰或异常处理不足，可能导致协同冲突和误动作。

### 适用范围
适用于机器人与 PLC 及自动化外设协同的通用逻辑；实际信号地址和时序以现场控制方案为准。
'@
        }
        "robot_安全_001" {
@'
### 操作步骤
1. 在操作或集成前进行风险分析与风险评估，识别挤压、碰撞等危险。
2. 根据风险选择消除、防护或警示等控制措施。
3. 核对安全围栏、安全门联锁、急停装置、光幕或激光扫描器及限速控制等措施是否适用。
4. 确保机器人作业区与人员活动区有效隔离；进入防护区域前执行停机要求。

### 预期结果
作业开始前已识别主要风险，并落实与风险相匹配的隔离、防护或警示措施。

### 常见错误
未完成风险分析、未采取有效隔离，或在安全措施不到位时进入作业区，都会增加挤压和碰撞伤害风险。

### 适用范围
适用于工业机器人操作与集成前的通用安全准备；具体风险控制应遵循适用标准、现场规范和设备制造商要求。
'@
        }
        "robot_安全_002" {
@'
### 操作步骤
1. 区分人工触发的急停与由安全防护装置触发的保护性停止。
2. 检查急停和保护性停止是否通过安全相关电路实现，而非仅依赖软件逻辑。
3. 在适用的安全程序中定期测试停止功能的可靠性。
4. 发生安全相关控制系统故障时，按适用的 0 类或 1 类停止要求处理。

### 预期结果
能够识别两类停止功能的触发来源，并确认停止功能具备安全相关的实现与测试依据。

### 常见错误
把急停与保护性停止混为一谈，或仅依赖普通软件逻辑实现停止功能，会削弱安全控制的可靠性。

### 适用范围
适用于工业机器人停止功能的安全要求；停止类别、接线和测试方式必须以适用标准及设备制造商手册为准。
'@
        }
        default { "" }
    }
    if ($appendix) {
        $normalized = "$normalized`n`n$appendix".Trim()
    }
    # Plain labels retain classifier signals without splitting one knowledge point into chunks.
    $normalized = $normalized -replace '(?m)^###\s*操作步骤\s*$', '操作步骤：'
    $normalized = $normalized -replace '(?m)^###\s*预期结果\s*$', '预期结果：'
    $normalized = $normalized -replace '(?m)^###\s*常见错误\s*$', '常见错误：'
    $normalized = $normalized -replace '(?m)^###\s*适用范围\s*$', '适用范围：'
    return $normalized
}

function Assert-ImportMarkdown {
    param(
        [string]$Path,
        [int]$ExpectedCount,
        [hashtable]$KnownIds
    )

    $text = Get-Content -Raw -Encoding utf8 $Path
    $sections = [regex]::Matches($text, "(?m)^## (?!#).+$")
    if ($sections.Count -ne $ExpectedCount) {
        throw "$Path 应有 $ExpectedCount 个知识点，实际检测到 $($sections.Count) 个"
    }
    $ids = [regex]::Matches($text, '(?m)^- \*\*knowledge_id:\*\* `([^`]+)`$') |
        ForEach-Object { $_.Groups[1].Value }
    if ($ids.Count -ne $ExpectedCount) {
        throw "$Path 缺少结构化 knowledge_id"
    }
    foreach ($id in $ids) {
        if ($KnownIds.ContainsKey($id)) {
            throw "知识包内出现重复 knowledge_id: $id"
        }
        $KnownIds[$id] = $true
    }
    $weights = [regex]::Matches($text, '(?m)^- \*\*ability_weights:\*\* `(.+)`$') |
        ForEach-Object { $_.Groups[1].Value | ConvertFrom-Json }
    if ($weights.Count -ne $ExpectedCount) {
        throw "$Path 缺少 ability_weights"
    }
    foreach ($weight in $weights) {
        $sum = [double]$weight.theory + [double]$weight.practice + [double]$weight.problem_solving + [double]$weight.knowledge_breadth
        if ([math]::Abs($sum - 1.0) -gt 0.000001 -or [double]$weight.learning_speed -ne 0.0) {
            throw "$Path 中存在不符合导入规则的 ability_weights"
        }
    }
}

$sourcePackages = @(
    [pscustomobject]@{
        DomainCode = "ai_app_dev"
        DomainName = "人工智能应用开发实训"
        FileName = "01-ai-application-foundations.md"
        Title = "人工智能应用开发基础扩展"
        Items = @(
            @("kb-artificial-intelligence.json", "ai_AI概论_003", "aiapp.foundation.agent_environment.001"),
            @("kb-artificial-intelligence.json", "ai_机器学习_001", "aiapp.foundation.ml_paradigms.001"),
            @("kb-artificial-intelligence.json", "ai_机器学习_003", "aiapp.foundation.regularization.001"),
            @("kb-artificial-intelligence.json", "ai_机器学习_004", "aiapp.foundation.model_evaluation.001"),
            @("kb-artificial-intelligence.json", "ai_深度学习_001", "aiapp.foundation.neural_network.001"),
            @("kb-artificial-intelligence.json", "ai_深度学习_002", "aiapp.foundation.backpropagation.001"),
            @("kb-artificial-intelligence.json", "ai_自然语言处理_002", "aiapp.foundation.language_model.001"),
            @("kb-artificial-intelligence.json", "ai_自然语言处理_003", "aiapp.foundation.bert.001"),
            @("kb-artificial-intelligence.json", "ai_自然语言处理_004", "aiapp.foundation.gpt.001"),
            @("kb-artificial-intelligence.json", "ai_自然语言处理_005", "aiapp.foundation.llm_scaling.001"),
            @("kb-artificial-intelligence.json", "ai_自然语言处理_006", "aiapp.foundation.llm_limitations.001"),
            @("kb-ml-basics.json", "ml_深度学习基础_001", "aiapp.foundation.tensor_operations.001"),
            @("kb-ml-basics.json", "ml_深度学习基础_002", "aiapp.foundation.data_preprocessing.001"),
            @("kb-ml-basics.json", "ml_深度学习基础_005", "aiapp.foundation.autodiff.001"),
            @("kb-ml-basics.json", "ml_大语言模型_llm_001", "aiapp.foundation.word_embedding.001"),
            @("kb-ml-basics.json", "ml_大语言模型_llm_006", "aiapp.foundation.subword_bpe.001"),
            @("kb-ml-basics.json", "ml_自然语言处理_nlp_002", "aiapp.foundation.text_preprocessing.001"),
            @("kb-ml-basics.json", "ml_自然语言处理_nlp_003", "aiapp.foundation.language_model_dataset.001"),
            @("kb-ml-basics.json", "ml_自然语言处理_nlp_020", "aiapp.foundation.multi_head_attention.001"),
            @("kb-ml-basics.json", "ml_自然语言处理_nlp_021", "aiapp.foundation.self_attention_position.001"),
            @("kb-ml-basics.json", "ml_自然语言处理_nlp_022", "aiapp.foundation.transformer_core.001"),
            @("kb-python-data-analysis.json", "pyda_Python基础_002", "aiapp.foundation.python_types.001"),
            @("kb-python-data-analysis.json", "pyda_Python基础_003", "aiapp.foundation.python_control_flow.001"),
            @("kb-python-data-analysis.json", "pyda_Python基础_004", "aiapp.foundation.python_functions.001"),
            @("kb-python-data-analysis.json", "pyda_Python基础_005", "aiapp.foundation.jupyter_notebook.001")
        )
    },
    [pscustomobject]@{
        DomainCode = "smart_manufacturing"
        DomainName = "智能制造实训"
        FileName = "01-manufacturing-overview.md"
        Title = "智能制造总览与制造系统"
        Items = @(
            @("kb-smart-manufacturing.json", "im_总览与体系_001", "sm.overview.001"), @("kb-smart-manufacturing.json", "im_总览与体系_002", "sm.overview.002"),
            @("kb-smart-manufacturing.json", "im_总览与体系_003", "sm.overview.003"), @("kb-smart-manufacturing.json", "im_总览与体系_004", "sm.overview.004"),
            @("kb-smart-manufacturing.json", "im_数字化设计_001", "sm.overview.005"), @("kb-smart-manufacturing.json", "im_数字化设计_003", "sm.overview.006"),
            @("kb-smart-manufacturing.json", "im_数字化设计_005", "sm.overview.007"), @("kb-smart-manufacturing.json", "im_数字化设计_006", "sm.overview.008"),
            @("kb-smart-manufacturing.json", "im_制造执行_001", "sm.overview.009"), @("kb-smart-manufacturing.json", "im_制造执行_003", "sm.overview.010"),
            @("kb-smart-manufacturing.json", "im_制造执行_005", "sm.overview.011"), @("kb-smart-manufacturing.json", "im_制造执行_006", "sm.overview.012"),
            @("kb-smart-manufacturing.json", "im_工业物联网_001", "sm.overview.013"), @("kb-smart-manufacturing.json", "im_工业物联网_002", "sm.overview.014"),
            @("kb-smart-manufacturing.json", "im_工业物联网_005", "sm.overview.015"), @("kb-smart-manufacturing.json", "im_工业物联网_006", "sm.overview.016"),
            @("kb-smart-manufacturing.json", "im_工业物联网_008", "sm.overview.017"), @("kb-smart-manufacturing.json", "im_工业智能_001", "sm.overview.018"),
            @("kb-smart-manufacturing.json", "im_工业智能_002", "sm.overview.019")
        )
    },
    [pscustomobject]@{
        DomainCode = "smart_manufacturing"
        DomainName = "智能制造实训"
        FileName = "02-industrial-connectivity.md"
        Title = "工业互联网与连接基础"
        Items = @(
            @("kb-industrial-internet.json", "ii_总览与体系_001", "sm.connectivity.001"), @("kb-industrial-internet.json", "ii_总览与体系_002", "sm.connectivity.002"),
            @("kb-industrial-internet.json", "ii_总览与体系_003", "sm.connectivity.003"), @("kb-industrial-internet.json", "ii_网络体系_001", "sm.connectivity.004"),
            @("kb-industrial-internet.json", "ii_网络体系_002", "sm.connectivity.005"), @("kb-industrial-internet.json", "ii_网络体系_003", "sm.connectivity.006"),
            @("kb-industrial-internet.json", "ii_网络体系_004", "sm.connectivity.007"), @("kb-industrial-internet.json", "ii_标识解析_001", "sm.connectivity.008"),
            @("kb-industrial-internet.json", "ii_标识解析_006", "sm.connectivity.009")
        )
    },
    [pscustomobject]@{
        DomainCode = "smart_manufacturing"
        DomainName = "智能制造实训"
        FileName = "03-plc-control.md"
        Title = "PLC 控制与组态"
        Items = @(
            @("kb-plc-basics.json", "plc_PLC基础_001", "sm.plc.001"), @("kb-plc-basics.json", "plc_PLC基础_002", "sm.plc.002"),
            @("kb-plc-basics.json", "plc_PLC基础_003", "sm.plc.003"), @("kb-plc-basics.json", "plc_PLC基础_004", "sm.plc.004"),
            @("kb-plc-basics.json", "plc_梯形图编程_001", "sm.plc.005"), @("kb-plc-basics.json", "plc_梯形图编程_002", "sm.plc.006"),
            @("kb-plc-basics.json", "plc_梯形图编程_003", "sm.plc.007"), @("kb-plc-basics.json", "plc_梯形图编程_004", "sm.plc.008"),
            @("kb-plc-basics.json", "plc_梯形图编程_005", "sm.plc.009"), @("kb-plc-basics.json", "plc_梯形图编程_006", "sm.plc.010"),
            @("kb-plc-basics.json", "plc_梯形图编程_007", "sm.plc.011"), @("kb-plc-basics.json", "plc_程序结构_001", "sm.plc.012"),
            @("kb-plc-basics.json", "plc_程序结构_002", "sm.plc.013"), @("kb-plc-basics.json", "plc_模拟量处理_001", "sm.plc.014"),
            @("kb-plc-basics.json", "plc_模拟量处理_002", "sm.plc.015"), @("kb-plc-basics.json", "plc_TIA实操_001", "sm.plc.016"),
            @("kb-plc-basics.json", "plc_TIA实操_002", "sm.plc.017"), @("kb-plc-basics.json", "plc_TIA实操_003", "sm.plc.018"),
            @("kb-plc-basics.json", "plc_TIA实操_004", "sm.plc.019")
        )
    },
    [pscustomobject]@{
        DomainCode = "smart_manufacturing"
        DomainName = "智能制造实训"
        FileName = "04-industrial-robot-operation.md"
        Title = "工业机器人操作与安全"
        Items = @(
            @("kb-industrial-robot.json", "robot_机器人基础_001", "sm.robot.001"), @("kb-industrial-robot.json", "robot_机器人基础_002", "sm.robot.002"),
            @("kb-industrial-robot.json", "robot_机器人基础_003", "sm.robot.003"), @("kb-industrial-robot.json", "robot_机器人基础_004", "sm.robot.004"),
            @("kb-industrial-robot.json", "robot_示教编程_001", "sm.robot.005"), @("kb-industrial-robot.json", "robot_示教编程_002", "sm.robot.006"),
            @("kb-industrial-robot.json", "robot_示教编程_004", "sm.robot.007"), @("kb-industrial-robot.json", "robot_示教编程_005", "sm.robot.008"),
            @("kb-industrial-robot.json", "robot_示教编程_007", "sm.robot.009"), @("kb-industrial-robot.json", "robot_IO与执行器_001", "sm.robot.010"),
            @("kb-industrial-robot.json", "robot_IO与执行器_002", "sm.robot.011"), @("kb-industrial-robot.json", "robot_IO与执行器_003", "sm.robot.012"),
            @("kb-industrial-robot.json", "robot_安全_001", "sm.robot.013"), @("kb-industrial-robot.json", "robot_安全_002", "sm.robot.014")
        )
    }
)

# Source groups keep selection reviewable, while the import surface stays to one file per domain.
$aiApplicationPackage = @($sourcePackages | Where-Object { $_.DomainCode -eq "ai_app_dev" })[0]
$smartManufacturingItems = @(
    $sourcePackages |
        Where-Object { $_.DomainCode -eq "smart_manufacturing" } |
        ForEach-Object { $_.Items }
)
$packages = @(
    $aiApplicationPackage,
    [pscustomobject]@{
        DomainCode = "smart_manufacturing"
        DomainName = "智能制造实训"
        FileName = "01-smart-manufacturing-complete.md"
        Title = "智能制造实训完整知识包"
        Items = $smartManufacturingItems
    }
)

# Public source pages were fetched on 2026-08-30.  URLs are pinned to immutable Git commits.
$publicPracticeItems = @(
    [pscustomobject]@{
        domain_code = "smart_manufacturing"; knowledge_id = "sm.simulation.openplc_runtime_v4.001"
        name = "OpenPLC Runtime v4 容器化部署与编辑器连接"; category = "PLC 仿真与集成"; difficulty = 3
        tags = @("openplc", "runtime", "docker", "iec-61131-3", "simulation")
        source_title = "OpenPLC Runtime v4 README (commit bf82b1b)"; source_commit = "bf82b1b661fd95c9899969f629d692b77b4e1454"; source_blob_sha = "b90f2ab9a4c5774f343309036514754dcbc02463"
        source_url = "https://github.com/Autonomy-Logic/openplc-runtime/blob/bf82b1b661fd95c9899969f629d692b77b4e1454/README.md"
        license_note = "MIT License; public repository; captured 2026-08-30"
        ability_weights = [ordered]@{ theory = 0.20; practice = 0.50; problem_solving = 0.20; knowledge_breadth = 0.10; learning_speed = 0.0 }
        content = @'
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
'@
    },
    [pscustomobject]@{
        domain_code = "smart_manufacturing"; knowledge_id = "sm.robot.ur_ros2_installation.001"
        name = "UR ROS 2 Driver 安装与实时通信边界"; category = "机器人仿真与集成"; difficulty = 3
        tags = @("universal-robots", "ros2", "driver", "network", "realtime")
        source_title = "Universal Robots ROS 2 Driver installation (commit f6cae59)"; source_commit = "f6cae596ae0ba7a5045a89b1e847c47155d7e203"; source_blob_sha = "0ba605065d3d22f3dbf6955a1edea1b6e6d99983"
        source_url = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/installation/installation.rst"
        license_note = "BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30"
        ability_weights = [ordered]@{ theory = 0.20; practice = 0.45; problem_solving = 0.25; knowledge_breadth = 0.10; learning_speed = 0.0 }
        content = @'
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
'@
    },
    [pscustomobject]@{
        domain_code = "smart_manufacturing"; knowledge_id = "sm.robot.ursim_driver_simulation.001"
        name = "URSim 与 UR ROS 2 Driver 联合仿真"; category = "机器人仿真与集成"; difficulty = 3
        tags = @("universal-robots", "ursim", "ros2", "rviz", "simulation")
        source_title = "Universal Robots ROS 2 Driver simulation (commit f6cae59)"; source_commit = "f6cae596ae0ba7a5045a89b1e847c47155d7e203"; source_blob_sha = "4a80b5fa5c83c4a70163fddd8ea7428b72fdbe99"
        source_url = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/usage/simulation.rst"
        license_note = "BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30"
        ability_weights = [ordered]@{ theory = 0.15; practice = 0.50; problem_solving = 0.25; knowledge_breadth = 0.10; learning_speed = 0.0 }
        content = @'
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
'@
    },
    [pscustomobject]@{
        domain_code = "smart_manufacturing"; knowledge_id = "sm.robot.ur_ros2_driver_startup.001"
        name = "UR ROS 2 Driver 启动与控制模式衔接"; category = "机器人仿真与集成"; difficulty = 4
        tags = @("universal-robots", "ros2", "driver", "external-control", "controller")
        source_title = "Universal Robots ROS 2 Driver startup (commit f6cae59)"; source_commit = "f6cae596ae0ba7a5045a89b1e847c47155d7e203"; source_blob_sha = "d696c4b2b9b2b35ef91c61df60206d438bd47d8"
        source_url = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/usage/startup.rst"
        license_note = "BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30"
        ability_weights = [ordered]@{ theory = 0.20; practice = 0.45; problem_solving = 0.25; knowledge_breadth = 0.10; learning_speed = 0.0 }
        content = @'
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
'@
    },
    [pscustomobject]@{
        domain_code = "smart_manufacturing"; knowledge_id = "sm.robot.ur_calibration_validation.001"
        name = "UR ROS 2 运动学校准提取与校验"; category = "机器人仿真与集成"; difficulty = 4
        tags = @("universal-robots", "ros2", "calibration", "kinematics", "validation")
        source_title = "Universal Robots ROS 2 Driver robot setup and startup (commit f6cae59)"; source_commit = "f6cae596ae0ba7a5045a89b1e847c47155d7e203"; source_blob_sha = "2c5c1821a7c824362227043eedefa0708fe17ce6, d696c4b2b9b2b35ef91c61df60206d438bd47d8"
        source_url = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/tree/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc"
        license_note = "BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30"
        ability_weights = [ordered]@{ theory = 0.25; practice = 0.40; problem_solving = 0.25; knowledge_breadth = 0.10; learning_speed = 0.0 }
        content = @'
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
'@
    },
    [pscustomobject]@{
        domain_code = "smart_manufacturing"; knowledge_id = "sm.robot.ur_external_control_recovery.001"
        name = "UR External Control 中断识别与恢复"; category = "机器人仿真与集成"; difficulty = 4
        tags = @("universal-robots", "ros2", "external-control", "recovery", "safety")
        source_title = "Universal Robots ROS 2 Driver startup recovery (commit f6cae59)"; source_commit = "f6cae596ae0ba7a5045a89b1e847c47155d7e203"; source_blob_sha = "d696c4b2b9b2b35ef91c61df60206d438bd47d8"
        source_url = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Driver/blob/f6cae596ae0ba7a5045a89b1e847c47155d7e203/ur_robot_driver/doc/usage/startup.rst"
        license_note = "BSD-3-Clause License; Universal Robots public repository; captured 2026-08-30"
        ability_weights = [ordered]@{ theory = 0.20; practice = 0.35; problem_solving = 0.35; knowledge_breadth = 0.10; learning_speed = 0.0 }
        content = @'
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
'@
    }
)

if (-not (Test-Path -LiteralPath $KnowledgeZip -PathType Leaf)) {
    throw "未找到知识压缩包: $KnowledgeZip"
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$archive = [System.IO.Compression.ZipFile]::OpenRead($KnowledgeZip)
try {
    $datasets = @{}
    foreach ($datasetName in ($packages.Items | ForEach-Object { $_[0] } | Select-Object -Unique)) {
        $datasets[$datasetName] = @{}
        foreach ($record in Read-ArchiveDataset -Archive $archive -Name $datasetName) {
            $datasets[$datasetName][$record.knowledge_id] = $record
        }
    }

    $manifest = @()
    $knownIds = @{}
    foreach ($package in $packages) {
        $domainDirectory = Join-Path $OutputDirectory $package.DomainCode
        New-Item -ItemType Directory -Path $domainDirectory -Force | Out-Null
        $targetPath = Join-Path $domainDirectory $package.FileName
        $lines = [System.Collections.Generic.List[string]]::new()
        $lines.Add("# $($package.Title) ($($package.DomainCode))")
        $lines.Add("")
        $lines.Add("本文件由 knowledge.zip 的结构化资料整理而成。每个二级标题对应一个可增量维护的知识点；请勿修改 knowledge_id。")
        $lines.Add("")
        $index = 0
        foreach ($selection in $package.Items) {
            $index++
            $datasetName, $sourceId, $targetId = $selection
            $record = $datasets[$datasetName][$sourceId]
            if ($null -eq $record) {
                throw "找不到选定的原始知识点: $datasetName / $sourceId"
            }
            if ([string]::IsNullOrWhiteSpace($record.source_title) -or [string]::IsNullOrWhiteSpace($record.source_url) -or [string]::IsNullOrWhiteSpace($record.license_note)) {
                throw "原始知识点缺少来源或许可信息: $sourceId"
            }
            $weights = Get-AbilityWeights -DomainCode $package.DomainCode -Category $record.category
            $tags = @($record.tags | ForEach-Object { [string]$_ }) + "source_record:$sourceId"
            $lines.Add("## $index. $($record.name)")
            $lines.Add("- **knowledge_id:** ``$targetId``")
            $lines.Add("- **category:** $($record.category)")
            $lines.Add("- **difficulty:** $($record.difficulty)")
            $lines.Add("- **tags:** $($tags -join ', ')")
            $lines.Add("- **source:** [$($record.source_title)]($($record.source_url))")
            $lines.Add("- **license:** $($record.license_note)")
            $lines.Add("- **ability_weights:** ``$($weights | ConvertTo-Json -Compress)``")
            $lines.Add("")
            $lines.Add((Convert-ContentForStructuredMarkdown -Content $record.content -SourceId $sourceId))
            $lines.Add("")
        }
        $externalItems = @($publicPracticeItems | Where-Object { $_.domain_code -eq $package.DomainCode })
        foreach ($record in $externalItems) {
            $index++
            $lines.Add("## $index. $($record.name)")
            $lines.Add("- **knowledge_id:** ``$($record.knowledge_id)``")
            $lines.Add("- **category:** $($record.category)")
            $lines.Add("- **difficulty:** $($record.difficulty)")
            $lines.Add("- **tags:** $($record.tags -join ', '), public_source_commit:$($record.source_commit)")
            $lines.Add("- **source:** [$($record.source_title)]($($record.source_url))")
            $lines.Add("- **license:** $($record.license_note); source_blob_sha=$($record.source_blob_sha)")
            $lines.Add("- **ability_weights:** ``$($record.ability_weights | ConvertTo-Json -Compress)``")
            $lines.Add("")
            $lines.Add($record.content.Trim())
            $lines.Add("")
        }
        $knowledgeCount = $package.Items.Count + $externalItems.Count
        [System.IO.File]::WriteAllText($targetPath, (($lines -join "`n").TrimEnd() + "`n"), [System.Text.UTF8Encoding]::new($false))
        Assert-ImportMarkdown -Path $targetPath -ExpectedCount $knowledgeCount -KnownIds $knownIds
        $manifest += [pscustomobject]@{
            domain_code = $package.DomainCode
            file = "$($package.DomainCode)/$($package.FileName)"
            knowledge_count = $knowledgeCount
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetPath).Hash.ToLowerInvariant()
        }
    }

    $readmeLines = @(
        '# 可导入知识包',
        '',
        "生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')",
        '',
        '这些 Markdown 已按系统结构化导入格式校验。每个知识点包含稳定 knowledge_id、类别、难度、标签、来源、许可与能力权重。正文来源于原始 JSON；原正文中的标题已转为粗体标签，避免被解析为额外知识点。',
        '智能制造包中的 TIA Portal、机器人示教、I/O 协同与安全条目已将原始正文中明确给出的流程、结果、错误和适用边界结构化为普通标签行；未新增设备按钮、地址、命令或参数等原文未支持的事实。',
        '另加入 6 条从 OpenPLC Runtime v4 和 Universal Robots 官方公开仓库提炼的仿真与集成知识。每条固定到 Git 提交、源文件 URL 与 Blob SHA；详细来源见 public-source-manifest.json。',
        '',
        '## 导入顺序',
        '',
        '1. `ai_app_dev/01-ai-application-foundations.md`：在现有“人工智能应用开发实训”领域中以增量模式上传。导入完成后，在变更集内完成候选校验、图谱、Candidate 索引和题库缺口补齐，再一次启用。',
        '2. 新建领域 `smart_manufacturing`，名称为“智能制造实训”，上传 `smart_manufacturing/01-smart-manufacturing-complete.md`，并在同一变更集中完成发布。',
        '3. 知识发布后，从题库管理下载系统生成的 XLSX 缺口模板，填写题目、来源绑定并通过认证；不得预先手写题库模板。',
        '',
        '## 稳定 ID 规则',
        '',
        '- 后续编辑同一知识点时保留 `knowledge_id`，系统将其识别为更新候选。',
        '- 新知识点应新增 `knowledge_id`，不要复用或改写历史 ID。',
        '- 常规上传是新增/更新，不会因为新文件缺少旧章节而删除已发布知识。替换或撤回旧资料必须走显式操作。',
        '',
        '## 内容范围',
        '',
        '- `ai_app_dev` 包含 25 个与 AI 应用开发直接相关的基础点，不导入视觉、强化学习、完整优化算法等会扩大正式题库维护范围的条目。',
        '- `smart_manufacturing` 包含 67 个智能制造、工业互联网、PLC 和工业机器人知识点，其中 14 条具备可识别的操作、验收与错误处理证据，用于演示领域迁移。',
        '',
        '## 文件清单与校验和',
        ''
    )
    foreach ($item in $manifest) {
        $readmeLines += "- ``$($item.file)``：$($item.knowledge_count) 个知识点，SHA-256 ``$($item.sha256)``"
    }
    [System.IO.File]::WriteAllText((Join-Path $OutputDirectory "README.md"), (($readmeLines -join "`n").TrimEnd() + "`n"), [System.Text.UTF8Encoding]::new($false))
    $manifest | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $OutputDirectory "manifest.json")
    $publicPracticeItems | Select-Object knowledge_id, name, category, source_title, source_url, source_commit, source_blob_sha, license_note |
        ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $OutputDirectory "public-source-manifest.json")
    Write-Output "已生成并校验 $($manifest.Count) 份可导入文档，共 $($manifest.knowledge_count | Measure-Object -Sum | Select-Object -ExpandProperty Sum) 个知识点。"
}
finally {
    $archive.Dispose()
}
