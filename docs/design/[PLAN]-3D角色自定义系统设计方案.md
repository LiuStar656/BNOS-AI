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

*本文档基于 [PLAN]-3D角色自定义系统设计，技术参考：`@pixiv/three-vrm`、`Three.js`、`VRM 标准规范 v1.0`。*
