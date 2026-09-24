# 本声 · Local ASR Input

[English](README.md) | **简体中文** · 国内镜像：[Gitee](https://gitee.com/larntin/local-asr-input)

**免费、开源、本地识别的 Windows 语音输入工具。**
按一下热键说话，本机 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 离线识别，在弹窗里改好错字，一键上屏到任意窗口：终端、编辑器、聊天框都行。
识别不花钱、录音不出本机；想让文字更规整，可以接上任意大模型自动整理（OpenAI / Anthropic 两种协议都支持）。

<p align="center">
  <img src="docs/images/zh/demo.gif" width="720" alt="演示：录音、识别、LLM 整理"><br>
  <sub>录音 → 识别 → ✦ LLM 整理 → 按 Enter 上屏</sub>
</p>

## 特点

- **本地识别**：faster-whisper 跑在自己电脑上，有 NVIDIA 显卡自动用 GPU，没有就用 CPU。录音只在内存里，识别完即丢弃，不写硬盘、不上传。
- **云端识别（可选）**：没有显卡、或者想要更准？把识别引擎切到云端 API：阿里百炼 `qwen3-asr-flash`、OpenAI `whisper-1`，或任何支持 OpenAI `/audio/transcriptions` 的服务。
- **先看后发**：识别结果先出现在弹窗里，可以改错字、接着说、换行，确认后才上屏，不会把错字直接打进终端。
- **上屏到原窗口**：按热键时记住你所在的窗口，确认后切回去用剪贴板粘贴，PowerShell / Windows Terminal / VS Code / 浏览器都能用。
- **✦ LLM 整理（可选）**：把口述内容整理成清晰的文字，顺手修正同音错字（如「单立」→「单例」）。支持 **OpenAI** 和 **Anthropic** 两种协议，各模型平台的接口地址 + Key 填上就能用；Ctrl+Z 一步撤回原文。
- **中文友好**：自动整理标点（`﹐﹑` → `，、`，挨着中文的英文标点转全角，代码里的不动）。
- **全部可配置**：快捷键（直接按键录入）、字号、Whisper 模型、LLM 协议 / 模型 / 整理规则，都在 ⚙ 设置里。
- **中英双语界面**：默认跟随系统语言，也可以在 ⚙ 设置 → 常规 → 界面语言里切换。
- **安静省心**：无边框深色弹窗，状态全靠图标和颜色；托盘常驻、只允许一个实例；日志按天轮转只留 7 天。

## 安装

### 直接下载（推荐）

1. 到 [Releases](https://github.com/larntin/local-asr-input/releases) 下载 `LocalASRInput-v*-win64.zip`，解压到任意位置。
2. 运行 `LocalASRInput.exe`，右下角托盘出现麦克风图标；`config.json` 和日志生成在 exe 旁边。
3. 第一次运行会从 HuggingFace 下载 Whisper 模型（`large-v3-turbo` 约 1.6GB）。国内下载慢或下载不动时，先执行一次 `setx HF_ENDPOINT https://hf-mirror.com` 再重新启动；或者在 ⚙ 设置里改用云端识别。

**显卡**：有 NVIDIA 显卡、并装了 CUDA 12 运行库（cuBLAS）时自动用显卡识别；没有就自动改用 CPU，能用但慢一些。没有显卡的电脑推荐用云端识别。

### 从源码运行

需要 **Windows 10/11**、**Python 3.10+**。

```bash
git clone https://github.com/larntin/local-asr-input.git
# 国内访问 GitHub 慢的话，用 Gitee 镜像：
# git clone https://gitee.com/larntin/local-asr-input.git
cd local-asr-input
pip install -r requirements.txt
```

启动：双击 `start.bat`（后台运行，看右下角托盘的麦克风图标），或者 `python local_asr_input.py`（带控制台，方便看日志）。


## 使用

| 按键 | 作用 |
|---|---|
| **F9** | 开始录音；再按一次结束录音并识别。弹窗开着时再按 = 接着说，插到光标处 |
| **Enter** | 上屏：粘贴到按 F9 时所在的窗口（不回车，回车你自己按） |
| **Shift+Enter** | 换行 |
| **Ctrl+L** / 点 ✦ | 用 LLM 整理文本框里的内容（Ctrl+Z 撤回） |
| **Esc** | 取消（LLM 整理中按 = 放弃这次整理） |
| **Ctrl+Alt+F9** | 退出程序（也可以托盘右键退出） |

以上快捷键都可以在 ⚙ 设置里改：点一下输入框，直接按下想要的组合键。

**状态看图标**：左下角 + 窗口底边的色带

| 样子 | 状态 |
|---|---|
| 红色跳动的音量条 | 录音中 |
| 橙色流动小块 | 识别中 |
| 紫色流动小块 | LLM 整理中 |
| 绿色圆点 | 可以编辑、上屏 |
| 灰色空心圈 | 没识别到内容 / 太短 |
| 红色空心圈 | 出错了（详见日志） |

## 设置

点弹窗右下角的 ⚙，或托盘右键「设置」。保存后立即生效，不用重启。换识别模型时会在后台重新加载，托盘图标变灰，加载好就能用。

<p align="center">
  <img src="docs/images/zh/settings-llm.png" width="420" alt="LLM 设置">
  <img src="docs/images/zh/settings-general.png" width="420" alt="常规设置">
</p>

### 云端语音识别（可选）

在 ⚙ 设置 → 常规里把**识别引擎**切到**云端 API**，然后填：

| 接口类型 | 适用 | 示例 |
|---|---|---|
| 聊天接口 + 音频 | 阿里百炼 Qwen3-ASR | `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型 `qwen3-asr-flash` |
| OpenAI 转写接口（`/audio/transcriptions`） | OpenAI、Groq 等兼容 OpenAI 的服务 | `https://api.openai.com/v1`，模型 `whisper-1` |

接口地址和 Key 的填法和 LLM 一样（地址可以填 URL 或环境变量名，Key 放在环境变量里）。保存前可以点「测试连接」。用云端时不会加载本地 Whisper 模型，启动很快，也不需要显卡。

### 接入大模型（可选）

不配置也完全能用，只是没有 ✦ 整理功能。配置方法：

1. 在模型平台拿到**接口地址**和 **API Key**（阿里百炼、火山方舟、腾讯混元、DeepSeek、OpenAI、Anthropic 等都可以）。
2. 把 Key 放进一个**环境变量**（Key 不会写进配置文件），例如：
   ```bash
   setx BAILIAN_API_KEY "sk-你的key"
   ```
3. 在 ⚙ 设置 → ✦ LLM 里选协议（OpenAI / Anthropic），填模型名、接口地址（可以直接填 URL，也可以填存放 URL 的环境变量名）、Key 所在的环境变量名，点「测试连接」确认能通，再保存。

两种协议各自保存一套配置，切换不会互相覆盖。以阿里百炼为例：

| 协议 | 接口地址 |
|---|---|
| OpenAI | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Anthropic | `https://dashscope.aliyuncs.com/apps/anthropic` |

「识别完成后自动用 LLM 整理」默认开启：只整理新说的那一段，少于 6 个字的不整理；**没配置好 LLM 时自动跳过**，什么也不会发出去。

## 隐私

- 默认的本机识别：录音只在内存里，在本机完成识别，不写硬盘、不上传。
- 如果把识别引擎切到**云端 API**，每段录音会发给你配置的服务商。
- 只有开启了 ✦ LLM 整理时，识别出的**文字**才会发给你配置的模型平台。
- 日志默认会记录识别出的文字，方便排查问题；介意的话在 ⚙ 设置 → 常规 → 日志级别选「仅错误和警告」。日志只保留最近 7 天。

## 配置文件

所有设置保存在程序目录的 `config.json`（第一次运行自动生成，里面有 `_说明`）。一般用 ⚙ 设置改就行，不用手动编辑。

## 开发

```bash
python tests/run_all.py     # 测试
pip install pyinstaller
python build.py             # 打包成 dist/LocalASRInput-v<版本>-win64.zip
```

测试会短暂弹出窗口，但不会模拟真实按键。`test_llm` / `test_auto_llm` / `test_protocol` 会真实调用 LLM，需要环境变量 `OPENAI_COMPAT_BASE_URL` 和 `BAILIAN_API_KEY`，没有时自动跳过。

## 计划

- [x] 云端语音识别（填 URL + Key），没有显卡的电脑也能用
- [x] 打包成 exe，下载即用，不用装 Python
- [x] Gitee 镜像：https://gitee.com/larntin/local-asr-input

## 许可证

[MIT](LICENSE)
