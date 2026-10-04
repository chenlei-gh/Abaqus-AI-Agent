# P1.1 多模态工程感知实现级契约审计与架构设计规范
# (P1.1 Implementation-Level Contract Audit & Architecture Specification)

**版本:** 2026-10-04  
**基线定位:** 针对现有代码 `contracts/multimodal.py`、`annotations/schema.py`、`contracts/geometry.py`、`grounding/multimodal.py` 的逐行真实契约核查  
**战略使命:** 彻底杜绝“审计说能复用、写代码发现字段不合”的返工隐患，锁定 Provider-Neutral 感知抽象、矢量优先 PDF 摄入、多维置信度门禁与最小新增接口清单。

---

## 一、现有核心代码真实契约核查 (Hard Facts & Contract Invariants)

在编写任何感知代码前，必须严格对齐当前 `main` 分支的强类型构造器与 `__post_init__` 断言：

### 1.1 `VisualCallout` 构造契约 (`src/abaqus_ai_agent/contracts/multimodal.py`)
```python
@dataclass(frozen=True)
class VisualCallout:
    callout_id: str                      # 必填，非空字符串
    callout_type: str                    # CalloutType 枚举值 ("ARROW", "TEXT", "DIMENSION", "SYMBOL", "REGION_BOX")
    location: ImagePoint                 # 必填，强类型 ImagePoint(x, y)，坐标必须严格在 [0.0, 1.0]
    direction_vector: Optional[Tuple[float, float]] = None # 可选，但若提供则模长严禁为 (0.0, 0.0)！
    region_box: Optional[ImageRegion] = None # 可选，必须为 ImageRegion(center=ImagePoint, width, height)！
    text_content: Optional[str] = None   # 提取的文本，如 "5 kN 向下"
    semantic_intent: Optional[str] = None# 语义枚举，如 "FIXED_SUPPORT", "PRESSURE", "CONCENTRATED_FORCE"
    magnitude: Optional[float] = None    # 标量物理数值
    unit: Optional[str] = None           # 单位字符串，如 "N", "MPa", "mm"
    metadata: Dict[str, Any] = field(default_factory=dict)
```
* **审计踩坑预警 (Pitfalls)**：
  1. `location` 必须是 `ImagePoint(x, y)` 实例，传入 `(0.5, 0.5)` 元组会导致类型错误；且若 $x, y < 0$ 或 $> 1$，会在 `ImagePoint.__post_init__` 中直接抛出 `ValueError("image coordinates must be in [0, 1]")`。
  2. `region_box` 必须是 `ImageRegion(center=ImagePoint(cx, cy), width=w, height=h)`，严禁传入常见的 `(ymin, xmin, ymax, xmax)` 四元组！
  3. `direction_vector` 若为 `(0.0, 0.0)` 会触发 `ValueError("direction_vector cannot be zero-length")`。

### 1.2 `GroundingObservation` 与 `correlate_callout_with_cad` (`grounding/multimodal.py`)
* `correlate_callout_with_cad(callout, candidates, view_projection=None, ...)` 接收已有的 `VisualCallout` 与 CAD 候选面/边列表；
* **内部已有置信度判定机制**：
  * 若无候选面：`uncertainty_reasons=["ZERO_CANDIDATES_FOUND"]`，`confidence=0.0`，`requires_confirmation=True`；
  * 若有多重候选面（如厚度方向两个平行面）：`uncertainty_reasons=["AMBIGUOUS_MULTI_CANDIDATE"]`，`confidence <= 0.60`，`requires_confirmation=True`；
  * 若仅单一候选面：继承候选面自身置信度，若 $< 0.85$ 自动置 `requires_confirmation=True`。

### 1.3 `MultimodalHITLWorkflow` 门禁状态机 (`grounding/multimodal.py`)
* `workflow.register_observation(obs)`：依据 `confidence < threshold` 或多候选自动标记 `NEEDS_CONFIRMATION`；
* `workflow.confirm(decision)`：工程师显式确认，指定确定的几何面或锚点坐标；
* `workflow.synthesize_specs(fail_closed=True)`：**若有任一挂起项，严格抛出 `HITLBlockedError`**，生成 `IntentBoundarySpec` 与 `IntentLoadSpec`。

---

## 二、P1.1 五大核心深水区架构决议

针对前序规划中的粗放设想，本次实现级审计做出以下五项工程纠偏决议：

```text
                                  P1.1 架构核心决议全景
                                            │
    ┌───────────────────┬───────────────────┼───────────────────┬───────────────────┐
    ▼                   ▼                   ▼                   ▼                   ▼
[ 1. Provider-Neutral ] [ 2. 提取器正交解耦 ] [ 3. 矢量优先 PDF ] [ 4. 视觉校验漏斗 ] [ 5. 多维置信度矩阵 ]
- BaseVisionProvider    - DimensionExtractor- Vector-First      - Raw Observation   - text_confidence
- 杜绝锁定单一模型      - BoundaryLoadExtract- Raster-Fallback   - 强类型归一化校验   - vector_confidence
- 支持离线测试桩与商用  - 几何与力学物理隔离- 完整保留页面坐标系- 拒绝未校验假事实 - cad_matching_conf
```

### 决议 1：Provider-Neutral 抽象适配层（杜绝模型硬编码）
严禁在业务代码中直接硬编码调用某一家具体云端或本地大模型。定义标准协议基类：
```python
class BaseVisionProvider(ABC):
    """Provider-neutral abstract interface for multimodal engineering vision & OCR."""

    @abstractmethod
    def extract_text_blocks(self, image_bytes: bytes, **kwargs) -> Sequence[RawTextObservation]:
        """Extract textual content with bounding boxes and model confidences."""
        ...

    @abstractmethod
    def detect_engineering_symbols(self, image_bytes: bytes, **kwargs) -> Sequence[RawSymbolObservation]:
        """Detect load arrows, support symbols, and dimension tick-marks."""
        ...
```
* **收益**：默认提供 `MockVisionProvider` 与基于规则的离线实现，确保 GitHub CI 与单元测试 100% 离线确定性运行；线上或生产环境可通过配置无缝挂载高端多模态 API。

### 决议 2：尺寸标注与载荷/约束提取器正交解耦
* **尺寸标注 (`DimensionExtractor`)**：面向几何体系。识别基准面、尺寸界线、引出线、公差框格（如 $\Phi 20 \text{ H7}$、板厚 $t=5$、跨度 $L=100$），生成 `CalloutType.DIMENSION`，用于辅助 CAD 模型尺寸核验与参数推断；
* **载荷与边界符号 (`BoundaryLoadExtractor`)**：面向力学工况体系。识别外力箭头（单向力、压力、扭矩）、固定支座符号（斜网格线）、简支铰链（小圆与支座），生成 `CalloutType.ARROW` / `CalloutType.SYMBOL`，用于生成边界条件与外力。
* 严禁将两类异构力学概念强行揉入单个所谓的 `symbol_extractor.py` 中。

### 3. PDF 原生工程图纸摄入分流 (Vector-First, Raster-Fallback)
工程 PDF 绝不能草率当成单张图片压平。必须支持两级分流：
1. **矢量优先提取 (Vector Extraction)**：
   * 优先提取 PDF 内部的原生矢量字符流（字体、文本块、坐标）与原生矢量线段（线条、引出线）；
   * 矢量文本识别率 100%，无 OCR 模糊与量纲解析失真。
2. **光栅化回退 (Rasterization Fallback)**：
   * 若页面为纯扫描图纸或含有手写批注/复杂三维渲染视图，自动以 $300\text{ DPI}$ 高分辨率光栅化为 PNG 图像，送入 Vision 引擎；
3. **空间坐标与溯源保全 (Provenance & Coordinate Transform)**：
   * 无论矢量还是光栅，均完整记录 `source_file`, `page_number`, `page_box`, `scale_factor`，确保提取的任何坐标均可逆映射回真实图纸。

### 决议 4：原始视觉感知到结构化 `VisualCallout` 的防伪校验链
Vision 模型输出的仅是不可靠的原始观察（`RawVisionObservation`），严禁直接作为工程结论。必须经过结构化校验漏斗：
$$\text{RawVisionObservation} \xrightarrow{\text{Sanitize \& Clamp}} \text{ImagePoint [0, 1]} \xrightarrow{\text{Unit Normalization}} \text{VisualCallout} \xrightarrow{\text{correlate}} \text{HITL Gate}$$
* **自动清洗与防伪校验**：
  * 坐标强制归一化并夹取至 $[0.0, 1.0]$；
  * 零长度矢量自动剔除或赋予默认法向；
  * 尺寸量纲统一映射至系统标准量纲（如将 $\text{kN} \to 1000\text{ N}$）；
  * 校验失败或矛盾项直接标记 `INVALID_OBSERVATION`，阻断流入。

### 决议 5：多维置信度门禁模型 (Multi-Dimensional Confidence Matrix)
废弃单一 `confidence < 0.95` 的简化假设。建立四维工程置信度模型：
```python
@dataclass(frozen=True)
class PerceptionConfidence:
    ocr_confidence: float        # 文字/数值识别可信度 (0.0 ~ 1.0)
    symbol_confidence: float     # 箭头/符号几何拓扑可信度 (0.0 ~ 1.0)
    unit_confidence: float       # 量纲一致性与单位合理性可信度 (0.0 ~ 1.0)
    spatial_alignment_confidence: float # 2D 图纸与 3D CAD 空间对齐可信度 (0.0 ~ 1.0)
    has_ambiguous_candidates: bool      # 是否存在多重几何候选

    @property
    def composite_score(self) -> float:
        return (0.3 * self.ocr_confidence +
                0.3 * self.symbol_confidence +
                0.2 * self.unit_confidence +
                0.2 * self.spatial_alignment_confidence)

    @property
    def requires_human_confirmation(self) -> bool:
        return (
            self.has_ambiguous_candidates
            or self.composite_score < 0.90
            or self.ocr_confidence < 0.85
            or self.unit_confidence < 0.90
        )
```
* 只要存在几何候选歧义，或任一关键维度置信度偏低，**一律 fail-closed 进入 `NEEDS_CONFIRMATION`**。

---

## 三、P1.1 最终精准新增代码架构清单

在保持高内聚、低耦合、正交解耦的前提下，P1.1 的最小新增包设计为 `src/abaqus_ai_agent/perception/`：

```text
src/abaqus_ai_agent/perception/
├── __init__.py                  # 模块导出与统一命名空间
├── contracts.py                 # 感知层私有契约 (RawTextObservation, RawSymbolObservation, PerceptionConfidence)
├── provider.py                  # Provider-Neutral 抽象基类 (BaseVisionProvider) 及 Mock/规则实现
├── ingestion.py                 # PDF 矢量抽取/光栅化分流，图像标准化与坐标保全
├── dimension_extractor.py       # 尺寸标注线、引出线与公差解析 (输出 CalloutType.DIMENSION)
├── boundary_load_extractor.py   # 载荷箭头与约束符号解析 (输出 CalloutType.ARROW/SYMBOL)
└── perception_pipeline.py       # 感知总流水线：调用提取器 -> 校验 -> 生成标准 VisualCallout -> 对接现有 GA-2B
```

### 数据流与现有主干 100% 闭环接口：
```python
# 1. 摄入图纸文件
document_pages = DocumentIngestionPipeline.load_document("drawing.pdf")

# 2. 提取并组装标准 VisualCallout
callouts = PerceptionPipeline(provider=my_vision_provider).process_page(document_pages[0])

# 3. 100% 直接复用现有 GA-2B 拓扑关联 (无需做任何修改)
for callout in callouts:
    obs = correlate_callout_with_cad(callout, cad_candidates, view_projection)
    hitl_workflow.register_observation(obs)

# 4. 100% 直接复用现有 HITL 门禁与意图编译
bcs, loads, regions = hitl_workflow.synthesize_specs(fail_closed=True)

# 5. 100% 直接复用现有 P1.0 产品主入口
result = agent.solve_requirement(engineering_intent)
```

---

## 四、实施级测试规划 (Zero Regression & Real Coverage)

为确保 P1.1 稳健落地，将编写以下专门测试套件：
1. `tests/test_perception_ingestion.py`：测试矢量 PDF 提取、纯图片光栅化、多页处理与坐标可逆映射；
2. `tests/test_perception_extractors.py`：测试尺寸与载荷提取器的正交性、物理单位归一化与非法坐标拦截；
3. `tests/test_perception_confidence_gate.py`：测试多维置信度矩阵，验证多候选、低 OCR 分数、单位歧义下的 100% fail-closed 拦截；
4. `tests/test_p1_multimodal_perception_e2e.py`：端到端验证真实工程图纸从 PDF/PNG 输入，经由 Perception $\to$ `VisualCallout` $\to$ GA-2B `GroundingObservation` $\to$ HITL 确认 $\to$ P1.0 求解器全链闭环。
