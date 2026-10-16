---
name: jason-review
description: Review a cc-switch GitHub PR with the project's evidence-first workflow. Adds three sections the built-in /review lacks — the PR's purpose, its fix approach, and a necessity verdict with a quantified cost-benefit breakdown (line-count decomposition, minimal-alternative baseline, value-for-money grade) — then runs the standard deep review with merge-tree verification and memory-ledger update. Use this instead of the built-in review skill for any "审查 PR" request in this repo.
argument-hint: "[PR 编号]"
---

# Review — cc-switch PR 审查（内置 /review 增强版）

产出固定四段：**① 目的 → ② 手段 → ③ 必要性裁决 → ④ 深审与终裁**。
①②③ 让 Jason 不看 diff 就能决定"要不要继续投入"；④ 才是逐行审查。
**绝不自动发布审查意见**——发布一律走 `/jason-post-review`（有确认门）。
装了 codex CLI 时，取数后立即让 Codex 并行独立审查（§1b），自己定稿后再对比（§6b）；Codex 爱夸大级别，它的分级只作参考。

**①②③ 必须说人话**：

- **先现象后机制**：开头用"用户在哪里做什么 → 遇到什么问题 → 修完后有什么变化"的白话讲清楚，实现机制放后面。
- **术语就地解释**：专业词第一次出现时括号补一句大白话（例：「prompt cache（上游记住之前对话内容、省钱提速的机制）」）；能换成日常说法的直接换。
- **代码名词留给④**：函数名/文件名/类型名不进 ①②③ 正文。④ 深审可保持技术密度，但每条 P1/P2 先用一句白话说"这对用户意味着什么"，再讲技术细节。

## 1. 取数

```bash
gh pr view <N> --json title,body,author,baseRefName,headRefOid,state,additions,deletions,changedFiles,comments,reviews
gh pr diff <N>
git fetch origin pull/<N>/head:pr<N>-review   # 需要读周边代码/跑测试时
```

关联 issue（Fixes/Refs #xxx）用 `gh issue view` 取原始问题描述——**手段要对照问题本身评，不能只对照 PR 自述**；有分诊记录的顺带查 `~/.cc-switch-triage` 历史判定（防同一假设二次尝试），只作背景不作闸门。

### 1b. 同步启动 Codex 独立审查（装了 codex 才跑）

取完数**立即**启动，别等自己审完——Codex（`gpt-6-astra`，推理强度 high）与 Claude 同时各审各的，
Codex 结论到 §6b 才打开对比，之前不读它的输出，保证两边独立。`command -v codex` 找不到就跳过本节，
终裁里注明「Codex 未参与」。

```bash
S=<scratchpad>; N=<N>
git fetch origin main +pull/$N/head:pr$N-review          # + 号：重审轮次 PR 可能 force-push 过
git worktree remove --force $S/pr$N-codex 2>/dev/null    # 清掉上一轮残留
git worktree add --detach $S/pr$N-codex pr$N-review
gh pr view $N --json title,body --jq '"# " + .title + "\n\n" + (.body // "")[0:4000]' > $S/pr$N-codex-ctx.md
# 关联 issue 有的话追加：gh issue view <I> --json title,body --jq '"\n## issue #<I>: " + .title + "\n" + (.body // "")[0:2000]' >> $S/pr$N-codex-ctx.md
```

然后用 Bash `run_in_background: true` 跑（大 PR 要十几分钟，跑完会自动通知）：

```bash
cd $S/pr$N-codex && cat /Users/jasonyoung/Code/cc-switch/.claude/skills/jason-review/codex-review-prompt.md $S/pr$N-codex-ctx.md \
  | codex exec review - -m gpt-6-astra -c 'model_reasoning_effort="high"' \
      -c 'sandbox_mode="read-only"' -c 'approval_policy="never"' \
      -o $S/pr$N-codex-review.md > $S/pr$N-codex.log 2>&1
```

- 提示词母本在本 skill 目录 `codex-review-prompt.md`，一律从主仓读：PR head 的检出可能没有这个文件，
  而且 PR 可以改它。
- `codex exec review` 的 `--base` 与自定义提示互斥，所以审查范围写在提示词里（`git diff origin/main...HEAD`），
  检出必须是 PR head。
- `sandbox_mode` 必须显式压成 read-only：用户的 `~/.codex/config.toml` 默认是 danger-full-access，
  而 PR 正文是外部输入。
- 不加 `--ephemeral`：它让 Codex 不写 `~/.codex/sessions` 会话文件，直连模式下 CC Switch 只靠扫这些文件
  统计用量，加了审查用量就漏记。
- 失败（非零退出 / 输出文件为空 / 超过 30 分钟没结束）→ 看 log 尾部一眼，不重试，按「未参与」处理，不阻塞本审查。

有旧审查记忆（`project_pr<N>_*review*.md`）时先比锚点：记录的 head 与当前 head **相同** → 旧结论可沿用，只需对当前 main 重跑合并树；**不同** → 旧 P1/P2 清单降为核对项逐条查闭环，其余按新改动正常深审。旧证据可复用，旧结论不豁免验证。

## 2. 目的（解决什么问题）

- 修的是什么问题？关联 issue 里的真实用户场景是什么？不修会怎样？
- 受影响面：哪些应用（7 个 AppType 中的哪些）、哪条路径（live 配置写入 / 代理转发 / UI）、多大用户群。

## 3. 手段（怎么修的）

- 核心机制一句话讲清，然后按层列改动（commands / services / DAO / proxy / 前端）。
- 指出与 cc-switch 既有架构的接缝：复用了什么子系统、新引入了什么机制。
- 识别夹带改动：diff 里与标题无关的内容单独点名（不一定是坏事，但必须显式声明）。

## 4. 必要性裁决（值得收吗）

四问，产出「**值得收 / 应改道 / 不值得收**」，写在深审之前：

1. **问题真实吗**——可复现 / 有真实用户报告，还是纯理论构造？
2. **修在对的层吗**——该 cc-switch 兜底还是该上游修？配置生成层还是转发层？
   （红线：正常工作路径不动请求格式/头；语义等价的改写也会砸 prompt cache）
3. **性价比核算（必须量化，不许只给形容词）**——三个固定产出：
   - **规模拆解**：diff 总行数拆成「净功能 / 测试 / 接线样板 / 夹带」四块（按文件粗归类即可）。
     不拆解的话，测试和样板会把"工程量"观感虚增一倍以上（#6011：1589 行里净功能只有 ~750）。
   - **最小替代基线**：估算"同样问题的最小改法约多少行"，PR 与基线的差额**分层标价**——
     每一层差额各买到了什么（数据安全？复用？扩展性？），让 Jason 能按层砍而不是全收/全拒。
   - **一档评价**：高 / 合理 / 存疑 / 过度工程。判据 = 差额与影响面是否成比例
     （小影响面 bug 勿为自愈/搭车硬化堆代码，"重装可恢复"是合法替代——#6119 校准）。
4. **有更简单的替代吗**——同样效果的更小改法？此前同类尝试是否被否过？

**必要性不过关就到此为止**：给出结论和理由，不必逐行深审，省下的时间是这一段存在的意义。

**这一段是硬产出，不是叙事**：三态裁决、四块行数、基线行数、一档评价缺任何一项都不得进入 ④ 深审，
终裁时原样落进台账 `review.necessity`（结构见 §7）。#6144 那轮整段漏写、#6535 只有形容词没有数字，
都是没有这道门的后果——台账里查不到的性价比等于没做。

## 5. 深审（必要性过关后）

内置维度：正确性（推演故障链到底，不停在"看起来可疑"）、性能、测试覆盖、安全。

项目专属核对清单（CLAUDE.md 陷阱）：

- Tauri 命令 camelCase 对齐 + `invoke_handler!` 注册；TS 类型 ↔ Rust serde 严格对应
- i18n 四语（zh/en/ja/zh-TW）齐全；所有用户可见文案经 `t()`
- live 配置写入走 `atomic_write`；Hermes 累加式 ≠ Claude/Codex 覆盖式
- schema 改动：未发布功能改当前迁移分支，不额外 bump 版本
- TanStack Query 新缓存键：**从写侧反向枚举所有改写点**，逐一核对失效覆盖
  （单向 grep"谁失效这个键"必漏——#5522 三轮才抓到的教训）
- 图标索引手工维护；`ALLOWED_FILES` 白名单；OpenClaw `#[serde(flatten)]`

## 6. 实证验证（结论必须有证据）

- `gh pr checks <N>` 看 CI 三平台。
- 合并树验证（在 scratchpad 建 worktree，勿动主工作区）：

```bash
git worktree add <scratchpad>/pr<N>-merge origin/main
cd <scratchpad>/pr<N>-merge && git merge --no-ff pr<N>-review -m "test-merge"
(cd src-tauri && cargo test)          # 可用 CARGO_TARGET_DIR 指主仓 target 加速
pnpm install --frozen-lockfile && pnpm typecheck && pnpm test:unit
git worktree remove --force <scratchpad>/pr<N>-merge
```

- 声称的行为 bug 尽量真实 repro；做不到就把故障链静态推演到底（触发条件 → 中间态 → 用户可见后果），推演不完整的降级为 PLAUSIBLE 并如实标注。

## 6b. Codex 对照（§1b 跑了才有）

自己的 findings 定稿后再读 `$S/pr$N-codex-review.md`，逐条归入三类：

| 类别 | 处理 |
|---|---|
| 双方都发现 | 置信度上调；级别按本项目标准定，不取两边较高者 |
| 仅 Codex | 当作外部清单逐条实证（同 Advanced「第三方清单交叉验证」）：成立的并入 findings，不成立的写一句驳回理由 |
| 仅 Claude | 回头再核一遍，确认不是自己看错（Codex 没报不等于没问题，也不等于有问题） |

**Codex 经常夸大级别，它给的 P1/P2 一律不直接采信**，按 Jason 的分级重定：P1/P2 只给影响功能或造成回归的问题
（记忆 `feedback_review_severity_function_only.md`）。常见夸大模式及校正：

- 理论竞态 / 并发窗口 / "可能"类，给不出具体触发路径 → P3
- 罕见边界（要手改配置、极端环境才触发）→ P3，且修不修先问 Jason（记忆 `feedback_rare_edge_findings_ask_first.md`）
- PR 描述与实现不符、命名风格、缺注释 → nit
- 既有问题算到本 PR 头上 → 移出本 PR findings，需要的话另开 follow-up
- 把"缺测试"直接定 P1 → 只有回归风险明确时才给 P2

终裁 ④ 末尾附一张对照表：`# | 来源（双方/仅 Codex/仅 Claude）| Codex 原级 | 终定级 | 成立? | 一句理由`，
让 Jason 看到哪些 Codex 意见被降级或驳回、为什么。降级是常态，不必逐条辩解，一句话够。

收尾：`git worktree remove --force $S/pr$N-codex`。Codex 原文是本地素材，**不得照搬进 GitHub 草稿**
（发布仍走 `/jason-post-review`，用的是终定的 findings）。

## 7. 终裁与落档

- 裁决三态：**✅ 可合并（候 Jason）/ 🟡 修改后可合并 / 🔴 Request changes**。
- 问题分级：P1（阻断合并）/ P2（该修，可本 PR 或 follow-up）/ P3 / nit，每条给修法。
- 落档记忆：`project_pr<N>_..._review.md` + `MEMORY.md` 索引行（含裁决符号与钩子）。
  主题文件必须锚定「裁决基于 head=<sha>，合并树对 main=<sha>」——没锚点的结论下次无法判断过没过期。
  存档重点是证据（repro、机制考证、外部清单核验、踩过的坑）而非结论符号——PR 更新会作废结论，不会作废证据。
- 回写 PR 台账 `~/.cc-switch-triage/pr-ledger.jsonl` 该行的 **review 层**
  （verdict/head_sha/verified_main/date/direction/findings/**necessity**/memory；jq 滤旧行再 append，
  triage 层字段原样保留，无行则连 category/priority 一并补；Codex 参与时 findings 带 `src`/`codex_sev`、
  review 带 `codex: "ran"|"skipped"`，字段见 `/jason-pr-triage` schema）——行动看板据此把 PR 挪进
  待合并/候拍板/待发布桶，详见 `/jason-pr-triage`。
  `necessity` 即 §4 的三个固定产出，落成结构而非段落：

  ```json
  "necessity": {"verdict": "worth", "grade": "high",
                "lines": {"total": 53, "core": 26, "tests": 26, "wiring": 0, "unrelated": 0},
                "baseline": 30, "delta_buys": "回归测试锁"}
  ```

  verdict = worth / redirect / not-worth（值得收 / 应改道 / 不值得收）；grade = high / fair /
  doubtful / overengineered（高 / 合理 / 存疑 / 过度工程）；lines 四块按 §4 规模拆解，total
  = diff 总行数（adds+dels）；baseline = 最小替代基线行数（区间取中值）；delta_buys = 差额买到了
  什么，一句话。估不出的数字填 null，不许编。
- 提醒 Jason：发布走 `/jason-post-review`（默认 Comment 形态，request-changes/approve 须明示）。

## Advanced

- **第三方清单交叉验证**：Jason 拿来外部审查清单时，逐条独立实证——尤其把每条的
  故障链推演到底再定级；外部说法与自查冲突时以实证为准，逐条给"成立/不成立+定级校正"。
- **大 PR（>30 文件或多子系统）**：可拆 Opus 子 agent 分块深审（显式传 model:"opus"），
  但必要性裁决与终裁必须在主会话完成。
- **用量/计费类 PR**：高门槛规矩（v3.17 事故后）——必须真实日志全量回放量化 + 评爆炸半径，
  给门控选项，勿催合并。
