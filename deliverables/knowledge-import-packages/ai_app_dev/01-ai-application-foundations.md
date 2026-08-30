# 人工智能应用开发基础扩展 (ai_app_dev)

本文件由 knowledge.zip 的结构化资料整理而成。每个二级标题对应一个可增量维护的知识点；请勿修改 knowledge_id。

## 1. 智能体与环境
- **knowledge_id:** `aiapp.foundation.agent_environment.001`
- **category:** AI概论
- **difficulty:** 2
- **tags:** agent, environment, perception, action, source_record:ai_AI概论_003
- **source:** [Russell & Norvig《人工智能：现代方法》(AIMA, 第4版, 2020)](http://aima.cs.berkeley.edu)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

智能体（Agent）是能够通过传感器感知环境、通过执行器对环境施加影响的系统。智能体的核心是感知—决策—行动的循环，其行为由感知序列到行动的映射（智能体函数）描述。根据环境特性，智能体所处的环境可分为完全可观测与部分可观测、确定性与随机性、静态与动态、离散与连续等类型，不同环境特性决定智能体需要采用不同的设计策略。理性智能体的目标是在给定感知与先验知识下，选择使期望效用最大化的行动。智能体框架是贯穿现代 AI（从专家系统到 LLM Agent）的统一视角。

## 2. 监督、无监督与强化学习
- **knowledge_id:** `aiapp.foundation.ml_paradigms.001`
- **category:** 机器学习
- **difficulty:** 2
- **tags:** supervised, unsupervised, reinforcement, paradigms, source_record:ai_机器学习_001
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

机器学习按训练信号分为三大范式。监督学习从带标签的样本中学习输入到输出的映射，用于分类与回归任务；无监督学习在无标签数据中发现内在结构，用于聚类、降维与密度估计；强化学习通过智能体与环境交互获得的奖励信号学习策略，目标是最大化长期累积回报。此外还有介于监督与无监督之间的半监督学习与自监督学习（如大模型的预训练）。选择何种范式取决于标签的可得性与任务目标，是机器学习建模的首要判断。

## 3. 过拟合与正则化
- **knowledge_id:** `aiapp.foundation.regularization.001`
- **category:** 机器学习
- **difficulty:** 3
- **tags:** overfitting, regularization, bias-variance, generalization, source_record:ai_机器学习_003
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

过拟合指模型在训练数据上表现很好、但在新数据上泛化能力差的现象，源于模型过度拟合训练样本中的噪声。过拟合与欠拟合、偏差-方差权衡密切相关：模型过于简单导致欠拟合（高偏差），过于复杂导致过拟合（高方差）。正则化是抑制过拟合的主要手段，通过在损失函数中加入对模型复杂度的惩罚（如 L1、L2 正则）约束参数，此外还有早停、数据增强、Dropout、增加训练数据等方法。控制模型复杂度以获得良好泛化，是机器学习的核心课题。

## 4. 模型评估与交叉验证
- **knowledge_id:** `aiapp.foundation.model_evaluation.001`
- **category:** 机器学习
- **difficulty:** 2
- **tags:** cross-validation, evaluation, metric, holdout, source_record:ai_机器学习_004
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

模型评估用于客观衡量模型的泛化能力。基本做法是把数据划分为训练集与测试集，在训练集上训练、在测试集上评估；当数据量较小或需要更稳定的估计时，采用 k 折交叉验证，将数据分成 k 份，轮流以其中一份为验证集、其余为训练集，取 k 次结果的平均。评估指标因任务而异：分类常用准确率、精确率、召回率、F1 与 ROC-AUC，回归常用均方误差等。评估需注意数据泄露、类别不平衡与评估集与训练集分布一致等问题，避免用测试集调参导致评估失真。

## 5. 神经网络与感知机
- **knowledge_id:** `aiapp.foundation.neural_network.001`
- **category:** 深度学习
- **difficulty:** 2
- **tags:** neural-network, perceptron, activation, mlp, source_record:ai_深度学习_001
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

人工神经网络由大量相互连接的神经元组成，每个神经元对输入加权求和后经激活函数输出。感知机是最简单的单层神经网络，能实现线性分类，但无法解决线性不可分问题（如异或）；多层感知机（MLP）通过引入隐藏层与非线性激活函数，使网络能够逼近任意复杂函数。常用激活函数包括 ReLU、Sigmoid、Tanh 等，非线性激活是神经网络具备强大表达能力的必要条件。神经网络的深度与宽度共同决定其容量，是深度学习的基础结构。

## 6. 反向传播算法
- **knowledge_id:** `aiapp.foundation.backpropagation.001`
- **category:** 深度学习
- **difficulty:** 3
- **tags:** backpropagation, chain-rule, gradient, training, source_record:ai_深度学习_002
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

反向传播是训练神经网络的核心算法，利用链式法则高效计算损失函数对网络中每个参数的梯度。训练过程包括前向传播（由输入计算输出与损失）与反向传播（由输出层向输入层逐层回传误差梯度）两个阶段，再利用梯度下降等优化算法更新参数。反向传播使深层网络的参数能够被有效训练，是现代深度学习的基石。其关键是计算图与链式法则，实践中还需处理梯度消失、梯度爆炸与数值稳定性等问题。

## 7. 语言模型与预训练
- **knowledge_id:** `aiapp.foundation.language_model.001`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** language-model, pretraining, transfer-learning, self-supervised, source_record:ai_自然语言处理_002
- **source:** [Devlin et al.《BERT: Pre-training of Deep Bidirectional Transformers》(2018)](https://arxiv.org/abs/1810.04805)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

语言模型是估计词序列概率分布的模型，本质是根据上文预测下一个词（补全续写）。预训练指在大规模语料上先训练模型获得通用语言知识，再迁移到下游任务。预训练的演进从静态词向量（Word2Vec）到上下文相关表示（ELMo、BERT），技术手段包括遮罩语言建模（MLM，完形填空）与下一句预测（NSP）等自监督任务。预训练—微调范式大幅提升了下游任务性能并降低了标注需求，是当代大语言模型能力的基础。

## 8. BERT 与双向编码
- **knowledge_id:** `aiapp.foundation.bert.001`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** bert, encoder, bidirectional, understanding, source_record:ai_自然语言处理_003
- **source:** [Devlin et al.《BERT: Pre-training of Deep Bidirectional Transformers》(2018)](https://arxiv.org/abs/1810.04805)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

BERT（2018）是基于 Transformer 编码器的预训练语言模型，采用双向编码，即同时利用上下文两侧信息理解每个词的语义，因此同一词在不同语境中具有不同的向量表示。BERT 通过遮罩语言建模与下一句预测两个自监督任务在大规模语料上预训练，再针对下游任务微调，显著提升了情感分类、命名实体识别、问答等自然语言理解任务的性能。BERT 代表编码器架构模型，擅长理解类任务，与擅长生成的 GPT 解码器架构形成互补。

## 9. GPT 与生成式预训练
- **knowledge_id:** `aiapp.foundation.gpt.001`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** gpt, decoder, generative, autoregressive, source_record:ai_自然语言处理_004
- **source:** [Brown et al.《Language Models are Few-Shot Learners》(GPT-3, 2020)](https://arxiv.org/abs/2005.14165)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

GPT 系列是基于 Transformer 解码器的生成式预训练语言模型，采用自回归方式逐词预测下一词，因而具有强大的文本生成能力。GPT 的演进体现了规模化的威力：GPT-1 验证预训练有效性，GPT-2 展示多任务泛化潜力，GPT-3 以千亿参数展现少样本学习（few-shot）能力，证明了模型与数据规模增大带来的能力涌现。GPT 代表解码器架构，与 BERT 的编码器架构形成理解与生成的互补，是 ChatGPT 等对话模型的技术基础。

## 10. 大语言模型的缩放法则
- **knowledge_id:** `aiapp.foundation.llm_scaling.001`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** scaling-law, llm, parameters, compute, source_record:ai_自然语言处理_005
- **source:** [Kaplan et al.《Scaling Laws for Neural Language Models》(2020)](https://arxiv.org/abs/2001.08361)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

缩放法则（Scaling Laws）揭示了大语言模型性能与资源投入之间的规律：在参数规模、数据规模与算力三者中任一项指数增长，都会带来模型性能（如损失）的线性提升，其贡献排序大致为参数规模、数据规模、算力。这意味着扩大模型与数据规模是提升性能的可靠路径，也解释了大模型的性能优势来源。但规模化带来巨大的训练成本与能耗，且性能提升存在边际递减，因此大模型的发展需要在规模、成本与能力之间权衡，也催生了高效训练、蒸馏与压缩等研究方向。

## 11. 大语言模型的能力与局限
- **knowledge_id:** `aiapp.foundation.llm_limitations.001`
- **category:** 自然语言处理
- **difficulty:** 2
- **tags:** emergence, few-shot, hallucination, limitation, source_record:ai_自然语言处理_006
- **source:** [Brown et al.《Language Models are Few-Shot Learners》(GPT-3, 2020)](https://arxiv.org/abs/2005.14165)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

大语言模型展现出涌现能力，即当规模超过一定阈值后出现小模型不具备的能力，如少样本学习、上下文学习、多任务与初步推理。这些能力使其成为通用任务的基础设施。但大语言模型也存在明显局限：可能生成看似合理但事实错误的内容（幻觉），缺乏真正的逻辑与因果推理，对训练数据中的偏差与有害信息可能继承与放大，且存在可解释性危机与较高的推理成本。理解其能力边界是负责任地使用大模型的前提，通常需通过检索增强、外部工具与人工审核等手段缓解其局限。

## 12. 张量数据操作基础
- **knowledge_id:** `aiapp.foundation.tensor_operations.001`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** tensor, ndarray, reshape, deep-learning, source_record:ml_深度学习基础_001
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_preliminaries/ndarray.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

深度学习中的数据以张量（tensor）形式存储，张量是多维数值数组，一维对应向量，二维对应矩阵，更高维没有特殊名称。深度学习框架的张量类（如PyTorch的Tensor、TensorFlow的Tensor）与NumPy的ndarray类似，但额外支持GPU加速和自动微分，因此更适合深度学习。创建张量时，可以用arange生成连续整数序列，默认创建为整数或浮点数，且除非指定，张量存储在CPU内存中。访问张量的形状用shape属性，元素总数用numel或size。改变形状而不改变元素数量和值时，使用reshape函数，可以指定目标维度，其中-1表示自动计算该维度大小。初始化张量时，可以用zeros、ones创建全0或全1张量，或从特定分布随机采样。理解张量的基本操作是进行深度学习计算的前提，后续章节会通过实例巩固这些概念。

## 13. 数据预处理基础
- **knowledge_id:** `aiapp.foundation.data_preprocessing.001`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** pandas, preprocessing, data, source_record:ml_深度学习基础_002
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_preliminaries/pandas.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

深度学习通常从预处理原始数据开始，而非直接使用张量。应使用pandas读取CSV等格式的数据，并注意缺失值以NaN表示。处理缺失值时，可以采用插值法（如用均值填充数值列）或删除法，但插值法更常用。对于类别值，应将NaN视为独立类别，并使用独热编码（如get_dummies）转换为数值列，避免模型误解类别含义。预处理后，需将pandas数据转换为张量格式以供模型使用。整个过程应确保数据清洗和特征工程合理，以提升模型训练效果。

## 14. 自动微分与反向传播
- **knowledge_id:** `aiapp.foundation.autodiff.001`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** autograd, backpropagation, computational-graph, source_record:ml_深度学习基础_005
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_preliminaries/autograd.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

自动微分是深度学习优化的核心，通过构建计算图跟踪数据与操作，系统能自动反向传播梯度，避免手工求导。使用框架时，需要为参数分配梯度存储空间，并注意默认行为：PyTorch和Paddle会累积梯度，每次反向传播前应清零；MXNet和TensorFlow则自动覆盖。梯度计算应验证正确性，例如对标量函数求导后检查结果是否符合解析解。当输出非标量时，梯度是矩阵或更高维张量，需明确求导目标。自动微分简化了复杂模型训练，但开发者需理解计算图机制和梯度管理，避免内存耗尽或梯度错误。

## 15. 词嵌入与word2vec
- **knowledge_id:** `aiapp.foundation.word_embedding.001`
- **category:** 词嵌入
- **difficulty:** 2
- **tags:** word2vec, skip-gram, CBOW, embedding, source_record:ml_大语言模型_llm_001
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_natural-language-processing-pretraining/word2vec.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

词嵌入是将词映射为实向量的技术，用于表示词义和特征，解决独热向量无法编码词间相似度的问题。word2vec包含跳元模型和连续词袋模型，均为自监督模型，通过条件概率训练。跳元模型假设中心词生成周围上下文词，每个词有中心词和上下文词两个向量，用softmax建模条件概率，训练时最大化似然函数，通常用中心词向量作为词表示。连续词袋模型假设上下文词生成中心词，对上下文词向量取平均，训练类似，通常用上下文词向量作为词表示。训练需注意词表大时梯度计算复杂度高，可考虑近似训练方法。

## 16. 子词嵌入与字节对编码
- **knowledge_id:** `aiapp.foundation.subword_bpe.001`
- **category:** 预训练
- **difficulty:** 2
- **tags:** subword, fasttext, bpe, source_record:ml_大语言模型_llm_006
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_natural-language-processing-pretraining/subword-embedding.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

子词嵌入通过利用词的内部形态结构来改进词向量表示，fastText是典型代表，它将每个中心词表示为字符n-gram向量的和，从而共享相似结构词的参数，使罕见词和词表外词也能获得较好向量。提取子词时需要在词首尾添加特殊字符以区分前缀后缀，并指定n-gram长度范围。字节对编码（BPE）是一种压缩算法，通过迭代合并最频繁的连续符号对来生成任意长度的子词，能适应固定词表大小，已用于GPT-2和RoBERTa等预训练模型的输入表示。实现BPE时应初始化符号词表为所有字符和特殊符号，统计词频时不考虑跨词边界，并在每个词尾附加特殊符号以便恢复原词序列。

## 17. 文本预处理流程
- **knowledge_id:** `aiapp.foundation.text_preprocessing.001`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** text-preprocessing, tokenization, vocabulary, source_record:ml_自然语言处理_nlp_002
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_recurrent-neural-networks/text-preprocessing.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

文本预处理是将原始文本转换为模型可操作的数字序列的核心步骤，通常包括四个环节：首先将文本作为字符串加载到内存中，并可以按需清洗，例如忽略标点符号和统一字母大小写；其次将字符串拆分为词元，词元可以是单词或字符，单词级拆分常用空格分割，字符级则直接列出每个字符；然后需要建立词表，将每个词元映射到唯一的数字索引，词表应覆盖训练数据中的所有词元；最后将文本转换为数字索引序列，以便模型直接读取。预处理时需要注意语料库规模，小语料库适合演示，但真实应用可能包含数十亿单词，因此处理流程应高效且可扩展。词元类型的选择会影响后续模型设计，字符级适合处理未知词或形态变化，单词级则保留更多语义信息，开发者应根据任务需求决定。

## 18. 语言模型与数据集
- **knowledge_id:** `aiapp.foundation.language_model_dataset.001`
- **category:** 基础概念
- **difficulty:** 2
- **tags:** language-model, probability, n-gram, smoothing, source_record:ml_自然语言处理_nlp_003
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_recurrent-neural-networks/language-models-and-dataset.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

语言模型的目标是估计文本序列的联合概率，通过逐词元采样可生成自然文本，但理想模型需理解语义而非仅语法。训练时，单词概率可由语料库词频估计，但罕见词组合因数据稀疏难以准确，需使用拉普拉斯平滑添加小常量以避免零计数。然而，基于计数的模型存储开销大、忽略词义，且长序列罕见，效果有限。马尔可夫假设可简化建模，如一阶假设当前词仅依赖前一词，对应一元、二元和三元语法模型。实际应用中，应优先考虑高频词统计，但需意识到简单频率方法对长依赖和语义理解不足，需结合更高级模型。

## 19. 多头注意力机制
- **knowledge_id:** `aiapp.foundation.multi_head_attention.001`
- **category:** 注意力机制
- **difficulty:** 3
- **tags:** multihead, attention, transformer, source_record:ml_自然语言处理_nlp_020
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_attention-mechanisms/multihead-attention.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

多头注意力通过并行学习多组独立的线性投影，将查询、键和值变换到不同子空间，并分别执行注意力汇聚，最后拼接各头输出并经线性投影得到最终结果。这种设计允许模型同时捕获序列内不同范围的依赖关系，如短距离和长距离依赖，从而表达比简单加权平均更复杂的函数。实现时通常选用缩放点积注意力作为每个头的基础，并设定各投影维度相等且等于输出维度除以头数，以控制计算和参数开销。若将线性变换输出维度设为头数与隐藏维度的乘积，则可并行计算所有头，提升效率。每个头可能关注输入的不同部分，组合后增强模型的表示能力。

## 20. 自注意力与位置编码
- **knowledge_id:** `aiapp.foundation.self_attention_position.001`
- **category:** 注意力机制
- **difficulty:** 2
- **tags:** self-attention, positional-encoding, sequence-modeling, source_record:ml_自然语言处理_nlp_021
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_attention-mechanisms/self-attention-and-positional-encoding.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

自注意力让同一序列的词元同时充当查询、键和值，每个查询关注所有键值对并输出等长序列，因此能直接建模任意位置间的依赖。相比卷积和循环网络，自注意力计算复杂度为O(n²d)，但顺序操作仅O(1)，最大路径长度为O(1)，更适合并行和捕捉远距离关系。然而自注意力本身不感知顺序，必须添加位置编码来注入序列位置信息。使用时应根据序列长度权衡计算开销，并确保位置编码与输入维度匹配。

## 21. Transformer架构核心
- **knowledge_id:** `aiapp.foundation.transformer_core.001`
- **category:** 注意力机制
- **difficulty:** 2
- **tags:** transformer, self-attention, encoder-decoder, source_record:ml_自然语言处理_nlp_022
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_attention-mechanisms/transformer.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"problem_solving":0.25,"knowledge_breadth":0.15,"learning_speed":0.0}`

Transformer完全基于注意力机制，摒弃了卷积和循环层，凭借自注意力的并行计算和最短路径优势成为现代深度学习的基础。其编码器由多个相同层叠加，每层包含多头自注意力和基于位置的前馈网络两个子层，均采用残差连接和层规范化，输入需加位置编码以保留序列顺序。解码器在编码器结构基础上，额外插入编码器-解码器注意力层，其中查询来自解码器前层，键和值来自编码器输出；解码器自注意力需使用掩蔽机制，确保每个位置仅能关注之前位置，维持自回归属性。基于位置的前馈网络对序列各位置应用同一MLP，实现逐位置的非线性变换。

## 22. 基本数据类型
- **knowledge_id:** `aiapp.foundation.python_types.001`
- **category:** Python基础
- **difficulty:** 1
- **tags:** data-type, list, dict, tuple, set, source_record:pyda_Python基础_002
- **source:** [Python 官方文档（Python 3 教程）](https://docs.python.org/zh-cn/3/)
- **license:** 官方文档; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

Python 的基本数据类型包括数值（整数 int、浮点数 float、复数 complex）、布尔 bool、字符串 str，以及容器类型：列表 list（有序可变）、元组 tuple（有序不可变）、字典 dict（键值对）、集合 set（无序不重复）。列表适合存放同质数据序列，字典适合键值查找与结构化数据，元组用于不可变的数据组合。掌握这些数据类型的特性与适用场景，是数据处理的基础，尤其是列表与字典在数据分析中的频繁使用。

## 23. 控制流
- **knowledge_id:** `aiapp.foundation.python_control_flow.001`
- **category:** Python基础
- **difficulty:** 1
- **tags:** control-flow, if, for, while, comprehension, source_record:pyda_Python基础_003
- **source:** [Python 官方文档（Python 3 教程）](https://docs.python.org/zh-cn/3/)
- **license:** 官方文档; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

Python 控制流包括条件判断（if-elif-else）与循环（for、while）。for 循环遍历序列或可迭代对象，是数据处理中最常用的循环结构；while 循环在条件满足时重复执行。Python 的列表推导式（comprehension）提供简洁的序列生成与变换方式，如 [x*2 for x in data]。在数据分析中，控制流用于数据的逐条处理、条件筛选与批量变换，但应优先使用向量化的 NumPy/Pandas 操作替代显式循环以提升性能。

## 24. 函数与模块
- **knowledge_id:** `aiapp.foundation.python_functions.001`
- **category:** Python基础
- **difficulty:** 1
- **tags:** function, module, import, def, source_record:pyda_Python基础_004
- **source:** [Python 官方文档（Python 3 教程）](https://docs.python.org/zh-cn/3/)
- **license:** 官方文档; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

函数用 def 定义，通过参数接收输入、return 返回结果，是代码复用与逻辑封装的基础。模块是 Python 代码的组织单元，通过 import 导入其他模块或包的功能。数据分析中大量使用 import numpy as np、import pandas as pd 等方式导入第三方库，并使用其中的函数与类。理解函数的参数传递、默认参数与返回值，以及模块的导入与使用，是编写可维护数据分析代码的基础。

## 25. Jupyter Notebook
- **knowledge_id:** `aiapp.foundation.jupyter_notebook.001`
- **category:** Python基础
- **difficulty:** 1
- **tags:** jupyter, notebook, repl, interactive, source_record:pyda_Python基础_005
- **source:** [Wes McKinney《利用Python进行数据分析》(第3版, 2022)](https://www.oreilly.com.cn)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"problem_solving":0.25,"knowledge_breadth":0.1,"learning_speed":0.0}`

Jupyter Notebook 是交互式的计算环境，以单元格为单位组织代码、文本与可视化输出，支持逐段执行与结果即时展示，是数据分析与探索的理想工具。Notebook 把代码、图表与说明文档整合在一起，便于复现分析过程与分享结果，广泛用于数据清洗、探索性分析与报告生成。其交互式特性适合数据探索时的反复试算，是数据分析工作流的重要组成部分。
