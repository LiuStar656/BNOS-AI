# 3D 角色自定义系统设计方案

> 日期：2026-07-27 | 版本：v1.0 | 状态：[PLAN]

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、技术架构](#三技术架构)
- [四、VRM 身体系统](#四vrm-身体系统)
- [五、SLOT 零件系统](#五slot-零件系统)
- [六、资产包格式](#六资产包格式)
- [七、表情与动画联动](#七表情与动画联动)
- [八、开发者工具链](#八开发者工具链)
- [九、Workshop 集成](#九workshop-集成)
- [十、用户操作流程](#十用户操作流程)
- [十一、与现有系统的关系](#十一与现有系统的关系)
- [十二、分阶段实施计划](#十二分阶段实施计划)
- [十三、风险评估](#十三风险评估)
- [十四、FAQ](#十四faq)
- [十五、验收方法](#十五验收方法)

---

## 一、背景与现状评估

### 现状

BNOS AI 当前的角色形象方案为 Live2D，在 `gui/main.py` 中通过 Live2D Cubism SDK 渲染。现存三个问题：

1. **定制成本高**：Live2D 模型需要画师绘制，一套 $50-500 元。用户想要"自己的 AI"但不愿承担此成本。
2. **零件化困难**：Live2D 是完整的角色文件，不支持换发型/换衣服的零件式定制。
3. **开发者门槛高**：要为 Live2D 做新衣服/发型，开发者需掌握 Live2D Cubism Editor（付费软件，$50+/年），且无法与 Three.js VRM 生态互通。

### 为什么不用纯 3D 写实

年轻人对纯 3D 写实画风接受度不高于二次元/三渲二风格。本方案采用 **VRM 三渲二模型 + Three.js MToon Shader（Cel Shading）**，实现原神/崩铁风格的角色渲染。

---

## 二、目标

1. **用户角度**：AI 的脸和身体永远不变（"这是我的 AI"），但发型、衣服、配饰可自由混搭，实时预览。
2. **开发者角度**：会 Blender 的人就能做零件，会 PS 的人也能参与（PNG 皮肤贴图）。零许可费用。
3. **平台角度**：零件通过 Steam Workshop 分发，开发者自主定价，平台抽成。
4. **技术角度**：沿用现有 PySide6 GUI，不换 Electron。QWebEngineView 内嵌 Three.js 渲染。

---

## 三、技术架构

```
┌─────────────────────────────────────────────────────┐
│ PySide6 GUI（桌面壳）                                │
│  ├─ 现有页面：聊天 / Live2D / 知识库 / 设置         │
│  ├─ QWebEngineView（Chromium 嵌入式浏览器窗口）      │
│  │   └─ Three.js 三渲二渲染器                       │
│  │        ├─ @pixiv/three-vrm（VRM 模型加载）        │
│  │        ├─ MToon Shader（Cel Shading 着色器）      │
│  │        ├─ Slot 零件管理（换头发/换衣服）          │
│  │        └─ BlendShape 表情驱动                    │
│  └─ Python 逻辑层                                    │
│       ├─ CharacterManager（资产管理 + 状态同步）      │
│       ├─ AssetScanner（复用 plugins_discovery）       │
│       └─ EmotionBridge（AAA 情绪 → Three.js 指令）    │
├─────────────────────────────────────────────────────┤
│ 外部工具链                                           │
│  ├─ VRoid Studio（免费） → 标准角色/身体             │
│  └─ Blender（免费）+ VRM Addon → 零件制作             │
└─────────────────────────────────────────────────────┘
```

### 为什么不用 Electron

| 维度 | Electron | PySide6 + QWebEngineView |
|------|---------|------------------------|
| 当前项目状态 | 需全部重写 | 现有 PySide6 88 行 GUI 直接复用 |
| 包体积 | +150MB（Chromium）| Qt 自带的 WebEngine，不额外增重 |
| 学习成本 | 重新学前端桌面开发 | 只需要加一个 WebView 组件 |
| 进程通信 | IPC 通道 | Python → `runJavaScript()` 直接调用 |

### 为什么不用 Python 原生 3D

| 维度 | Three.js (WebView) | Pure Python (PyOpenGL) |
|------|:----------------:|:---------------------:|
| GLB/GLTF 加载 | 原生 `GLTFLoader` | 自己写解析器 |
| VRM 加载 | `@pixiv/three-vrm` 官方库 | 无现成方案 |
| MToon 三渲二 | NPM 上现成 shader | 自己写 GLSL |
| 社区规模 | 百万级 | 千级 |

---

## 四、VRM 身体系统

### 4.1 什么是 VRM

VRM 是 Pixiv 主导的开源 3D 角色格式标准，专门为三渲二/二次元角色设计。它天然支持：

- 标准骨骼绑定（VRM Humanoid Bone）
- 表情 BlendShape（15 种 ARKit 标准表情）
- 材质参数（MToon Shader 内置）
- 一键加载，不需要额外配置

### 4.2 你需要的两份资产

| 资产 | 来源 | 用途 |
|------|------|------|
| **默认标准身体.vrm** | VRoid Studio 捏一个标准角色（免费，10 分钟） | 随软件内置，用户开箱即用 |
| **标准骨架.blend** | 导入默认 .vrm 到 Blender 后清理导出 | 给开发者的 Blender 模板 |

### 4.3 VRM 在 Three.js 中的加载

```javascript
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';

const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));
loader.load('default_body.vrm', (gltf) => {
  const vrm = gltf.userData.vrm;
  scene.add(vrm.scene);

  // 骨骼访问（零件挂载点）
  const head = vrm.humanoid.getBoneNode('head');
  const chest = vrm.humanoid.getBoneNode('chest');
  const hips = vrm.humanoid.getBoneNode('hips');
  const neck = vrm.humanoid.getBoneNode('neck');

  // 表情控制
  vrm.expressionManager.setValue('happy', 0.8);
  vrm.expressionManager.setValue('angry', 0.0);
});
```

### 4.4 VRM 只做身体底座

VRM 的角色包含完整身体，**但你只把它当底座**：

```
VRM 身体包含：
  ✅ Body mesh（身体+脸+皮肤贴图） → 保留，永不换
  ✅ 骨骼系统（head/chest/hips...）→ 保留，作为零件挂载点
  ✅ BlendShape（表情） → 保留，表情联动
  ✅ MToon 材质 → 保留，三渲二渲染

VRM 的额外 mesh：
  ❌ Hair mesh（头发） → 可隐藏，由零件替换
  ❌ 自带衣服 mesh → 可隐藏，由零件覆盖
```

---

## 五、SLOT 零件系统

### 5.1 Slot 定义

角色有 5 个独立槽位，每个槽位独立替换、自由混搭：

| Slot | 替换方式 | 开发者门槛 | 说明 |
|:----:|---------|:---------:|------|
| `hair` | 隐藏 VRM 原版头发 → 显示新发型 GLB | 需 Blender | 独立发型 mesh，绑到 head 骨骼 |
| `top` | 在 VRM 身体上叠加衣服 mesh | 需 Blender | 盖在身体上，绑到 chest/spine 骨骼 |
| `bottom` | 叠加下装 mesh | 需 Blender | 绑到 hips 骨骼 |
| `accessory` | 叠加配饰 mesh | 需 Blender | 绑到 head/neck 骨骼 |
| `skin_texture` | 替换 VRM Body 贴图 | **只需 PS** | 画 PNG 贴图，不建模 |

### 5.2 核心渲染逻辑（Three.js）

```javascript
class CharacterCustomizer {
  constructor(vrm) {
    this.vrm = vrm;
    this.scene = vrm.scene;
    this.slots = {
      hair: null,
      top: null,
      bottom: null,
      accessory: null,
    };
    this.hiddenParts = []; // VRM 自带的需要隐藏的 mesh
  }

  setPart(slotName, glbUrl) {
    // 1. 移除旧零件
    if (this.slots[slotName]) {
      this.scene.remove(this.slots[slotName]);
    }
    // 2. 加载新零件 GLB
    const loader = new GLTFLoader();
    loader.load(glbUrl, (gltf) => {
      const part = gltf.scene;
      this.slots[slotName] = part;
      // 3. 挂到对应骨骼上
      const bone = this._getTargetBone(slotName);
      bone.add(part);
    });
  }

  _getTargetBone(slotName) {
    const map = {
      hair: 'head',
      top: 'chest',
      bottom: 'hips',
      accessory: 'neck',
    };
    return this.vrm.humanoid.getBoneNode(map[slotName]);
  }

  setSkinTexture(pngUrl) {
    this.vrm.scene.traverse((child) => {
      if (child.isMesh && child.name === 'Body') {
        child.material.map = new THREE.TextureLoader().load(pngUrl);
        child.material.needsUpdate = true;
      }
    });
  }

  replaceHair(hairGlbUrl) {
    // 隐藏原版 VRM 头发
    this.vrm.scene.traverse((child) => {
      if (child.isMesh && (child.name.includes('hair') || child.name.includes('Hair'))) {
        child.visible = false;
        this.hiddenParts.push(child);
      }
    });
    // 加载新头发
    this.setPart('hair', hairGlbUrl);
  }
}
```

---

## 六、资产包格式

### 6.1 目录结构

```
assets/characters/
├── default_base/                    # 你提供的默认 VRM 身体（必有）
│   └── body.vrm
│
├── my_campus_outfit/               # 开发者张三的校园风服装包
│   ├── outfit.json                 # 描述文件
│   ├── top_school.glb              # 上衣 mesh
│   ├── bottom_skirt.glb            # 裙子 mesh
│   └── thumbnail.png               # 缩略图（创意工坊展示用）
│
├── twin_tail_hair/                 # 开发者李四的双马尾发型
│   ├── outfit.json
│   ├── hair_twin_tail.glb
│   └── thumbnail.png
│
└── summer_skin/                    # 开发者王五的皮肤贴图
    ├── outfit.json
    └── skin.png
```

### 6.2 outfit.json 格式

```json
{
  "asset_type": "character_parts",
  "name": "校园风服装包",
  "author": "张三",
  "version": "1.0.0",
  "compatible_spec": "vrm_humanoid_v1",

  "slots": {
    "top": {
      "file": "top_school.glb",
      "type": "mesh",
      "bone": "chest",
      "label": "上衣"
    },
    "bottom": {
      "file": "bottom_skirt.glb",
      "type": "mesh",
      "bone": "hips",
      "label": "下装"
    }
  },

  "tags": ["校园", "少女", "日系"],
  "thumbnail": "thumbnail.png",
  "price": 0
}
```

### 6.3 校验规则

| 校验项 | 规则 |
|--------|------|
| slot 名称 | 必须属于 `{hair, top, bottom, accessory, skin_texture}` |
| GLB 文件 | 必须存在，且为合法 GLTF 2.0 格式 |
| 骨骼绑定 | mesh 必须绑到 VRM 标准骨骼上，不能有浮动顶点 |
| thumbnail | 非必须，推荐 512x512 PNG |
| compatible_spec | 必须匹配当前版本 |

---

## 七、表情与动画联动

### 7.1 数据流

```
AAA 输出：{ "emotion": "HAPPY", "intensity": 0.8, "speaking": true }
  ↓
Python CharacterManager：
  webview.page().runJavaScript(
    f"vrmBridge.setEmotion('happy', 0.8); vrmBridge.setSpeaking(true);"
  );
  ↓
Three.js：
  vrm.expressionManager.setValue('happy', 0.8);
  vrm.expressionManager.setValue('angry', 0.0);
  // 说话张嘴动画（blendshape 'aa'）
  if (speaking) { mouthBlendShape = 0.3 + Math.random() * 0.3; }
```

### 7.2 VRM 标准表情映射

| AAA emotion | VRM BlendShape | 用户看到 |
|-------------|:--------------:|---------|
| NEUTRAL | neutral | 正常表情 |
| HAPPY | happy | 微笑/开心 |
| SAD | sorrow | 难过/委屈 |
| ANGRY | angry | 生气 |
| SURPRISED | surprise | 惊讶 |
| SPEAKING | aa / ih / ou（轮流） | 张嘴说话动画 |

### 7.3 说话口型

Three.js 每隔 100-200ms 随机切换 'aa' / 'ih' / 'ou' 三个 blendshape，模拟自然说话嘴动：

```javascript
let mouthTimer;
function startSpeaking() {
  const shapes = ['aa', 'ih', 'ou'];
  let i = 0;
  mouthTimer = setInterval(() => {
    // 清空所有口型
    ['aa', 'ih', 'ou'].forEach(s => vrm.expressionManager.setValue(s, 0));
    // 当前口型随机强度
    vrm.expressionManager.setValue(shapes[i], 0.3 + Math.random() * 0.4);
    i = (i + 1) % shapes.length;
  }, 120);
}
function stopSpeaking() {
  clearInterval(mouthTimer);
  ['aa', 'ih', 'ou'].forEach(s => vrm.expressionManager.setValue(s, 0));
  vrm.expressionManager.setValue('neutral', 1.0);
}
```

---

## 八、开发者工具链

### 8.1 你提供的工具

| 工具 | 内容 | 用途 |
|------|------|------|
| 标准骨架.blend | 已绑 VRM 骨骼的 Blender 模板 | 开发者建模的起点 |
| VRM 参考图 | 骨骼位置/尺寸标注图 | 开发者理解挂载位置 |
| 校验工具.py | 检查 GLB + outfit.json 合法性 | 上传前自检 |
| 模板 outfit.json | 标准的描述文件 | 开发者填空即可 |

### 8.2 开发者的完整工作流

```
1. 下载 标准骨架.blend（你提供）
   ↓
2. 在 Blender 中打开
   ↓
3. 做零件（三种方式选一种）：
   ┌─────────────────────────────────────────────┐
   │ 方式 A（新衣服）：                            │
   │   在身体外建模衣服 mesh → 绑定到对应骨骼       │
   │   → 导出为 .glb（只含衣服 mesh，不含身体）     │
   ├─────────────────────────────────────────────┤
   │ 方式 B（新发型）：                            │
   │   新建头发 mesh → 绑定到 head 骨骼            │
   │   → 导出为 .glb                              │
   ├─────────────────────────────────────────────┤
   │ 方式 C（新皮肤贴图，最低门槛）：                 │
   │   画一张 1024x1024 PNG 贴图                   │
   │   → 覆盖 VRM Body 贴图                        │
   └─────────────────────────────────────────────┘
   ↓
4. 写 outfit.json（拷贝模板，填空）
   ↓
5. 运行 校验工具.py 检查
   ↓
6. 打包 zip → 上传 Steam Workshop
```

### 8.3 开发者无需掌握的技能

| 不需要会 | 为什么 |
|---------|--------|
| Live2D Cubism | Three.js + GLB 方案，零许可 |
| VRM 打包工具 | VRM 身体你已提供，开发者只做 GLB 零件 |
| C# / Unity | 纯 Web 技术栈 |
| 3D 全流程 | 皮肤贴图方式（方式 C）只需要 PS |

---

## 九、Workshop 集成

### 9.1 与现有插件系统的关系

复用现有的 `plugins_discovery.py` 扫描逻辑：

| 插件系统 (plugins/) | 角色资产系统 (assets/characters/) |
|--------------------|---------------------------------|
| 扫描 `node_config.json` | 扫描 `outfit.json` |
| 合约匹配 `consumes` | slot 校验（合法 slot 名） |
| 注册到管线 | 注册到零件库 |
| 启动时生效 | 启动时可用，运行时切换 |

### 9.2 扫描逻辑

```python
class AssetScanner:
    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        self.part_registry = {}   # slot_name -> [part_def, ...]

    def scan(self):
        """扫描 assets/characters/ 目录"""
        for entry in os.scandir(self.assets_dir):
            outfit_path = os.path.join(entry.path, "outfit.json")
            if os.path.exists(outfit_path):
                with open(outfit_path, 'r') as f:
                    outfit = json.load(f)
                self._register_parts(entry.name, outfit)

    def _register_parts(self, pack_name: str, outfit: dict):
        """将零件注册到对应 slot"""
        for slot_name, part_info in outfit.get("slots", {}).items():
            if slot_name in VALID_SLOTS:
                self.part_registry.setdefault(slot_name, []).append({
                    "pack": pack_name,
                    "slot": slot_name,
                    "label": part_info.get("label", slot_name),
                    "file": part_info["file"],
                    "type": part_info["type"],
                    "thumbnail": outfit.get("thumbnail"),
                    "author": outfit.get("author", "unknown"),
                })
```

### 9.3 Workshop 订阅目录监听

Steam Workshop 订阅的 zip 文件自动下载到 `steam/workshop/content/[appid]/`，AssetScanner 监控此目录：

```python
class WorkshopMonitor:
    def __init__(self, workshop_dir: str, assets_target: str):
        self.watch_dir = workshop_dir
        self.target_dir = assets_target

    def on_new_subscription(self, zip_path: str):
        """Workshop 新订阅 → 解压到 assets/characters/"""
        pack_name = os.path.splitext(os.path.basename(zip_path))[0]
        extract_to = os.path.join(self.target_dir, pack_name)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_to)
        # 通知前端刷新零件列表
        self.notify_frontend_refresh()
```

---

## 十、用户操作流程

### 10.1 首次启动

```
第一次打开 BNOS AI
  ↓
GUI 显示默认 VRM 三渲二角色（你提供的标准身体）
  ↓
角色已经有默认发型和默认衣服
  ↓
用户可以立即开始使用，不需要配置

（角色定制是设置页功能，不是入门必经步骤）
```

### 10.2 角色定制界面

```
设置 → 角色外观
  ┌─────────────────────────────────────────┐
  │                                         │
  │      [ QWebEngineView ]                 │
  │      三渲二角色 3D 实时预览              │
  │      （可拖拽旋转、缩放查看）             │
  │                                         │
  ├─────────────────────────────────────────┤
  │                                         │
  │  发型：  [双马尾 ▼] [短发] [长发]  [🎲] │
  │  上衣：  [卫衣 ▼] [T恤] [衬衫]  [🎲]   │
  │  下装：  [短裤] [长裤] [裙子 ▼]  [🎲]  │
  │  配饰：  ☐眼镜  ☑猫耳  ☐项链           │
  │  皮肤：  [默认 ▼] [夏日限定]  [🎲]     │
  │                                         │
  │  ┌──────────────────────────────────┐   │
  │  │  [返回]        [保存穿搭 F1]       │   │
  │  └──────────────────────────────────┘   │
  │                                         │
  │  ▼ 已订阅零件包                         │
  │   校园风服装包 - 张三         [卸下]     │
  │   双马尾发型包 - 李四         [卸下]     │
  │   猫耳配饰 - 王五            [卸下]     │
  │                                         │
  │  📦 浏览创意工坊更多零件                 │
  └─────────────────────────────────────────┘
```

### 10.3 穿搭保存与切换

用户可以保存多套穿搭方案：

```json
// outfits/favorite_01.json
{
  "name": "日常校园风",
  "slots": {
    "hair": "twin_tail_hair",
    "top": "my_campus_outfit",
    "bottom": "my_campus_outfit",
    "accessory": "cat_ears",
    "skin_texture": null
  }
}

// outfits/favorite_02.json
{
  "name": "夏日清新",
  "slots": {
    "hair": "short_hair",
    "top": "summer_shirt",
    "bottom": null,
    "accessory": null,
    "skin_texture": "summer_skin"
  }
}
```

用户通过快捷键或切换按钮在已保存穿搭之间切换，角色实时换装。

---

## 十一、与现有系统的关系

### 11.1 Live2D 过渡方案

| 阶段 | 渲染方案 | 说明 |
|:----:|---------|------|
| Phase 1-2 | Live2D（现有） | 不动，新方案并行开发 |
| Phase 3 | **双渲染方案共存** | Live2D 保留，Three.js 新方案可选 |
| Phase 4+ | 推荐 Three.js，Live2D 降级 | 新用户默认 Three.js，旧用户自由选择 |

**现有 Live2D 代码不做删除**，仅在设置页提供切换选项。

### 11.2 与现有节点的关系

| 现有组件 | 变更 | 说明 |
|---------|:----:|------|
| `gui/main.py` | +QWebEngineView | 新增 Three.js 渲染窗口 |
| `gui/ui_settings.py` | +角色定制面板 | 新增零件选择和穿搭管理 |
| `node_js_live2d_face` | 不变（可选） | 保留现有功能 |
| `aaa_cognition` | +EmotionBridge | 情绪状态发送到 Three.js |
| `plugins_discovery.py` | 复用扫描逻辑 | 扫描 `assets/characters/` |
| `bnos_runtime/engine.py` | 无变更 | 角色系统不与引擎交互 |

---

## 十二、分阶段实施计划

### Phase 1 — Three.js 渲染集成（1 周）

| 任务 | 说明 |
|------|------|
| 在 GUI 中嵌入 QWebEngineView | 新建一个测试窗口，确认 WebView 能正常渲染 Three.js |
| 加载默认 VRM 模型 | 用 VRoid Studio 捏一个标准身体，导出 .vrm |
| 配置 MToon Shader 三渲二渲染 | 确保角色呈现二次元平涂风格 |
| 基础 OrbitControls（旋转/缩放） | 用户可拖拽查看角色 |

**交付**：Three.js + MToon 渲染的默认角色窗口，可代替 Live2D 显示。

### Phase 2 — Slot 零件系统（1 周）

| 任务 | 说明 |
|------|------|
| 实现 `setPart(slot, glbUrl)` | 加载 GLB → 挂到对应 VRM 骨骼 |
| 实现 `replaceHair(glbUrl)` | 隐藏原头发 + 显示新头发 |
| 实现 `setSkinTexture(pngUrl)` | 替换 VRM 身体贴图 |
| 零件缓存 | 已加载的零件不重复加载 |

**交付**：Three.js 角色可通过 JavaScript 指令换装。

### Phase 3 — Python 资产管理层（3 天）

| 任务 | 说明 |
|------|------|
| `AssetScanner` 扫描 `assets/characters/` | 读取 outfit.json → 注册零件 |
| `CharacterManager` 管理当前穿搭 | 保存/加载穿搭配置 JSON |
| `EmotionBridge` AAA 情绪 → WebView 指令 | Python -> JS 通信 |
| 表情联动调试 | AAA 输出 HAPPY → 角色微笑 |

**交付**：角色可以跟随对话情绪做出表情，零件可切换。

### Phase 4 — GUI 定制界面（3 天）

| 任务 | 说明 |
|------|------|
| 设置页添加"角色外观"Tab | 下拉列表选择零件，实时预览 |
| 穿搭保存/加载/切换 | 用户可保存多套风格 |
| 默认零件包（随软件内置 3-5 套） | 用户开箱即可换装体验 |

**交付**：用户在 GUI 中可直接操作换装。

### Phase 5 — 开发者工具 + Workshop（2 天）

| 任务 | 说明 |
|------|------|
| 标准骨架.blend 模板制作 | 开发者下载起点 |
| 校验工具.py | 开发者自检查 |
| Workshop 订阅目录监听 | Steam 下载 → 自动解压到 assets/characters/ |
| 开发者文档 | 规范 + 教程 |

**交付**：第三方开发者可制作并分发零件。

### Phase 6 — Live2D 切换 + 收尾（2 天）

| 任务 | 说明 |
|------|------|
| 设置页增加"渲染方案切换" | Live2D <-> Three.js |
| 性能优化 | GLB 缓存、贴图压缩 |
| 错误处理 | 不合法 GLB 不崩、显示占位 |

---

## 十三、风险评估

| 风险 | 影响 | 概率 | 缓解方案 |
|------|:----:|:----:|---------|
| QWebEngineView 性能不足（60fps 不稳定） | 高 | 低 | Qt 6 的 WebEngine 基于 Chromium，3D 渲染有 WebGL 硬件加速。现代集成显卡可稳定 60fps。 |
| VRM 模型兼容性问题（骨骼命名/权重） | 中 | 中 | 校验工具.py 检查骨骼是否存在标准命名；不匹配则降级为默认身体。**
| 开发者零件质量参差 | 中 | 高 | Workshop 评价系统自然筛选；提供官方校验工具前置检查。 |
| 用户不习惯 3D 角色 | 低 | 中 | 保留 Live2D 作为备选，默认 MToon 三渲二看起来接近 2D。 |
| Three.js WebView 包体积过大 | 低 | 低 | Three.js gzip 后约 120KB，@pixiv/three-vrm 约 40KB，合计不到 200KB。 |

---

## 十四、FAQ

**Q: 用户需要 VRoid Studio 或 Blender 才能自定义角色吗？**

不需要。普通用户不碰任何 3D 工具，在 BNOS AI 设置页的下拉菜单里选择零件即可。只有社区开发者（想做零件的人）需要 Blender 或 PS。

**Q: 默认角色长什么样？**

你用 VRoid Studio 10 分钟捏出来的一个标准角色。不需要好看，只要"标准人形"。用户开箱即用，后续可自由换装。

**Q: 零件之间会穿模吗？**

开发者做的零件基于同一个标准骨架，理论上位置一致。但无法 100% 避免穿模——这和模拟人生 CC 一样，部分 CC 穿模由评价系统筛选。质量差的零件不会流行。

**Q: 和 Live2D 哪个性能好？**

Three.js (WebGL) 的 3D 渲染比 Live2D 的 2D 骨骼动画消耗略高，但在现代电脑（2020 年后）上差异可忽略。老旧电脑仍推荐 Live2D。

**Q: 表情联动延迟高吗？**

AAA emotion -> Python -> WebView JS -> Three.js 整条链路在本地运行，延迟 < 50ms，用户无感。

---

## 十五、验收方法

### 15.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 64 位 |
| Python 运行时 | Python 3.10+，已安装 PySide6 |
| Qt 框架 | Qt 6.x，包含 QtWebEngine / QWebEngineView 组件 |
| 浏览器内核 | QtWebEngine 内置 Chromium，启用 WebGL 硬件加速 |
| GPU | 支持 WebGL 的显卡（集成显卡即可，如 Intel UHD / Iris Xe） |
| 前端依赖 | `three.js`、`@pixiv/three-vrm` 已打包至 GUI 资源目录 |
| 默认资产 | `assets/characters/default_base/body.vrm`（标准 VRM 身体）已内置 |
| 测试零件包 | 至少 1 个发型包、1 个服装包（含 top/bottom）、1 个皮肤贴图包，均符合 outfit.json 规范 |
| Steam Workshop | 测试订阅目录 `steam/workshop/content/[appid]/` 可读，含至少 1 个测试 zip 零件包 |
| AAA 情绪源 | 可输出 NEUTRAL/HAPPY/SAD/ANGRY/SURPRISED 情绪的测试桩或调试入口 |
| 校验工具 | `校验工具.py` 可独立运行 |
| 显示分辨率 | 1920×1080，60Hz 刷新率 |

### 15.2 功能验收用例

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | 默认 VRM 角色加载与渲染 | 1. 启动 BNOS AI；2. 进入主界面或"设置→角色外观" | QWebEngineView 内显示默认 VRM 角色，贴图完整，无白模/无贴图缺失 | 角色可见且贴图正确加载 | 核心 |
| F2 | MToon 三渲二风格确认 | 1. 加载默认 VRM；2. 观察角色表面渲染效果 | 角色呈现分块平涂、带轮廓线，符合二次元三渲二特征，非写实光照 | MToon Shader 生效，画面为二次元风格 | 核心 |
| F3 | OrbitControls 拖拽旋转/缩放 | 1. 在角色预览窗口鼠标左键拖拽；2. 滚轮缩放 | 角色 360° 旋转，视角缩放平滑，角色不丢失 | 旋转和缩放均响应且流畅 | 非核心 |
| F4 | hair 槽位换装 | 1. 进入"设置→角色外观"；2. 在"发型"下拉选择"双马尾" | 原 VRM 头发隐藏，新发型 GLB 加载并绑到 head 骨骼，实时显示 | 旧头发消失、新头发显示、位置正确 | 核心 |
| F5 | top/bottom/accessory 槽位换装 | 依次选择上衣、下装、配饰各一个零件 | 衣服 mesh 叠加到 chest/hips 骨骼，配饰绑到 neck/head 骨骼，均可见 | 三槽位零件正确挂载且位置合理 | 非核心 |
| F6 | skin_texture 皮肤贴图替换 | 1. 在"皮肤"下拉选择"夏日限定"；2. 观察身体贴图 | VRM Body 材质贴图被 PNG 替换，material.needsUpdate 生效 | 身体贴图切换为新 PNG，无闪烁残留 | 非核心 |
| F7 | replaceHair 隐藏原版头发 | 1. 加载一个 hair 零件；2. 通过调试控制台检查 VRM 自带 hair mesh 的 visible 状态 | VRM 原版 hair mesh.visible=false，hiddenParts 记录被隐藏对象 | 原版头发被隐藏且无残留 | 核心 |
| F8 | 零件缓存命中 | 1. 切换到发型 A；2. 切到发型 B；3. 切回发型 A | 第二次加载 A 时不重新发起 GLB 解析，秒级响应 | 缓存命中，二次加载明显更快 | 非核心 |
| F9 | AssetScanner 扫描注册 | 1. 在 `assets/characters/` 放入 ≥2 个合规零件包；2. 启动应用 | part_registry 按 slot 分组注册，下拉列表显示对应零件 | 所有合规零件均出现在对应槽位下拉 | 核心 |
| F10 | outfit.json 校验规则 | 1. 用 `校验工具.py` 分别校验合规包与 4 类不合规包（非法 slot 名/缺 GLB/骨骼未绑/compatible_spec 不匹配） | 合规包通过；4 类不合规包均报错并指出具体原因 | 5 类校验规则全部生效 | 非核心 |
| F11 | 穿搭保存与加载 | 1. 选定一套搭配；2. 点击"保存穿搭 F1"；3. 重启应用后加载该穿搭 | `outfits/*.json` 写入成功，重启后角色恢复该穿搭全部槽位 | 穿搭持久化且可完整还原 | 核心 |
| F12 | 多穿搭快速切换 | 1. 保存 ≥2 套穿搭；2. 通过快捷键/切换按钮在穿搭间切换 | 角色实时换装，无白屏闪烁，槽位状态正确 | 切换流畅且状态正确 | 非核心 |
| F13 | 表情联动 | 1. 通过 AAA 测试桩依次输出 HAPPY(0.8)/SAD/ANGRY/SURPRISED/NEUTRAL；2. 观察 VRM 表情 | happy/sorrow/angry/surprise/neutral BlendShape 值随情绪变化 | 5 种标准情绪均正确映射并实时变化 | 核心 |
| F14 | 说话口型动画 | 1. 触发 speaking=true 持续 5 秒；2. 触发 speaking=false | aa/ih/ou 每 100-200ms 轮流切换，停止后归零并回 neutral | 口型有动效且停止后复位 | 非核心 |
| F15 | Workshop 订阅目录监听 | 1. 在 `steam/workshop/content/[appid]/` 放入测试 zip；2. 观察 `assets/characters/` 与前端列表 | zip 自动解压到 `assets/characters/[包名]/`，前端零件列表刷新出现新零件 | 自动解压并刷新成功 | 非核心 |

### 15.3 边界与异常验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| E1 | 不合法 GLB 加载 | 1. 将一个损坏/非 GLTF 的 .glb 放入零件包；2. 在 UI 选择该零件 | 加载失败但不崩溃，显示占位/错误提示，其他槽位不受影响 | 异常隔离，不崩溃 | 核心 |
| E2 | 非法 slot 名 | 1. 构造 outfit.json 含 slot="hat"（不在合法集合）；2. 运行扫描 | 该 slot 被跳过/报错不注册，其他合法 slot 正常注册 | 非法 slot 被拒绝 | 核心 |
| E3 | 骨骼命名不匹配 | 1. 加载一个 GLB 其骨骼未使用 VRM 标准命名；2. 尝试挂载 | 零件挂载失败或降级为默认，给出骨骼缺失提示，无浮动顶点 | 不出现位置错乱/浮动顶点 | 核心 |
| E4 | 60fps 性能 | 1. 加载默认 VRM + 全槽位零件；2. 用 DevTools 或 FPS 计数监测 60 秒 | 平均帧率 ≥ 55fps，无持续卡顿 | 现代集显设备稳定接近 60fps | 非核心 |
| E5 | Live2D ↔ Three.js 切换 | 1. 在设置页切换渲染方案；2. 来回切换 3 次 | 两种方案均正常显示，切换不残留进程/资源 | 双向切换均可用 | 核心 |
| E6 | 空零件库降级 | 1. 清空 `assets/characters/` 仅保留 default_base；2. 启动应用 | 默认角色正常显示，下拉列表为空或仅显示默认，无报错 | 无零件时降级为默认身体 | 非核心 |
| E7 | 大量零件包扫描性能 | 1. 在 `assets/characters/` 放入 50 个零件包；2. 启动并计时扫描 | 扫描+注册完成时间 < 3 秒，UI 不长时间无响应 | 扫描在可接受时间内完成 | 非核心 |
| E8 | 表情联动端到端延迟 | 1. 触发情绪切换；2. 测量 AAA 输出 → Three.js 表情变化的时间差 | 延迟 < 50ms | 用户无感 | 非核心 |

### 15.4 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有"核心"项全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤2-3 项不通过且有补救计划 |
| **不通过** | 任一核心项不通过 |

#### 验收记录模板

```
================ 3D 角色自定义系统 验收记录 ================

功能名称：3D 角色自定义系统
验收日期：____年 __月 __日
验收人员：________________
验收版本：________________
验收环境：OS ______ / Python ______ / Qt ______ / GPU ______

【功能验收】
[ ] F1   默认 VRM 角色加载与渲染                         （核心）
[ ] F2   MToon 三渲二风格确认                            （核心）
[ ] F3   OrbitControls 拖拽旋转/缩放                     （非核心）
[ ] F4   hair 槽位换装                                   （核心）
[ ] F5   top/bottom/accessory 槽位换装                   （非核心）
[ ] F6   skin_texture 皮肤贴图替换                       （非核心）
[ ] F7   replaceHair 隐藏原版头发                        （核心）
[ ] F8   零件缓存命中                                    （非核心）
[ ] F9   AssetScanner 扫描注册                           （核心）
[ ] F10  outfit.json 校验规则                            （非核心）
[ ] F11  穿搭保存与加载                                  （核心）
[ ] F12  多穿搭快速切换                                  （非核心）
[ ] F13  表情联动                                        （核心）
[ ] F14  说话口型动画                                    （非核心）
[ ] F15  Workshop 订阅目录监听                           （非核心）

【边界与异常验收】
[ ] E1   不合法 GLB 加载                                 （核心）
[ ] E2   非法 slot 名                                    （核心）
[ ] E3   骨骼命名不匹配                                  （核心）
[ ] E4   60fps 性能                                      （非核心）
[ ] E5   Live2D ↔ Three.js 切换                          （核心）
[ ] E6   空零件库降级                                    （非核心）
[ ] E7   大量零件包扫描性能                              （非核心）
[ ] E8   表情联动端到端延迟                              （非核心）

【不通过项说明】
编号 | 现象描述 | 原因分析 | 补救计划
-----|---------|---------|--------
     |         |         |

【验收结论】
[ ] 通过
[ ] 附条件通过（不通过项及补救计划见上表）
[ ] 不通过

验收人签字：________________   日期：____年 __月 __日
============================================================
```

---

*本文档基于 [PLAN]-3D角色自定义系统设计，技术参考：`@pixiv/three-vrm`、`Three.js`、`VRM 标准规范 v1.0`。*
