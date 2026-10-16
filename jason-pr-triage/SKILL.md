---
name: jason-pr-triage
description: Sync GitHub PRs into the private local PR ledger (~/.cc-switch-triage), batch-classify open PRs into category + priority via an Opus workflow, and print derived action queues (merge-ready / needs-decision / re-verify / to-review / to-thank) so Jason can decide what to handle first. Review verdicts are written only by /jason-review; candid notes stay local — never posted to GitHub.
argument-hint: "[queue | stats | backfill N | <PR numbers…>] — 默认：增量同步 + 看板 + 分诊新 PR"
---

# PR Triage Ledger

GitHub 是 PR 事实的 SSOT；本台账只存 GitHub 上没有的**裁决增量**，分两层：

- **triage 层**（本 skill 批量写）：category / priority / candid note —— 回答"这是什么、该多快看"
- **review 层**（**只由 `/jason-review` 写**）：verdict + findings + necessity，锚定 head_sha —— 回答"审出了什么、值不值得收"

与 issue 台账的根本差异：issue verdict 单调推进，**PR 裁决是 sha 快照**——新 push 即作废。
因此 stale 与所有行动桶都是**派生态**（sync 现算 cache × ledger，永不入库），台账只存审时锚点。

```
~/.cc-switch-triage/
  pr-ledger.jsonl     # 裁决，一行一 PR —— 唯一权威记录
  cache/prs.jsonl     # GitHub 元数据镜像（sync.sh 生成，含 body 解析出的 fixes/refs；可重建勿手改）
  sync-state.json     # 与 issue 台账共用（本 skill 用 pr_last_synced_at 键）
```

## Schema

**pr-ledger.jsonl** 一行一条：

```json
{"number": 6510, "category": "bugfix", "priority": "P1", "priority_reason": "修已发版代理探测缺口", "modules": ["grok", "proxy"], "note": "candid 一句话", "review": {"verdict": "approve", "head_sha": "4af2c573", "verified_main": "b109dcd3", "date": "2026-08-17", "direction": "部分回撤 #6427 须 Jason 知情", "findings": [{"sev": "P2", "desc": "…", "status": "open"}], "necessity": {"verdict": "worth", "grade": "high", "lines": {"total": 248, "core": 43, "tests": 205, "wiring": 0, "unrelated": 0}, "baseline": 43, "delta_buys": "双向红绿回归测试"}, "memory": "project_pr6510_…_review.md"}, "published": null, "thanks": null, "triaged_at": "2026-08-21", "updated_at": "2026-08-21"}
```

- **category**：bugfix / feature / preset / perf / refactor / docs / i18n / ci / chore / revert
- **priority**（处理优先级=Jason 该多快看，非重要性）：
  P0 立即（已发版回归、数据安全/丢配置实锤、热根因组）→ P1 本周（实锤 bug、小修实锤、
  社区贡献者合格修复）→ P2 有空 → P3 挂起（方向存疑候拍板 / >60 天无活动 / 疑该关闭）。
  终态（merged/closed）后置 null。
- **review.verdict**：approve / approve-with-nits / request-changes / reject / pending-direction。
  **必须与 head_sha 同时写入**，无锚点的裁决视为无效；head_sha 存完整 40 位或 ≥8 位前缀均可
  （看板用前缀匹配比对 cache 的完整 sha）。轮次史留记忆主题文件（review.memory 指向），
  台账只存现值。direction = 需要 Jason 做的方向决策（独立于代码裁决）。
- **findings[].status**：open / fixed-in-pr / packaged-into-thanks / spawned:#N / dropped
- **findings[].src**（可选，/jason-review §6b 有 Codex 参与时写）：claude / codex / both；
  `codex_sev` = Codex 原给的级别（与终定 `sev` 不同时才写）。被驳回的仅 Codex 条目也落一条 `status: dropped`，
  用来统计 Codex 误报与夸大级别的比例；`review.codex` = ran / skipped 标记这一轮 Codex 是否参与
- **review.necessity**（/jason-review §4 必要性裁决的结构化落库，与 verdict 同时写入）：
  `verdict` worth / redirect / not-worth（值得收 / 应改道 / 不值得收）；
  `grade` high / fair / doubtful / overengineered（高 / 合理 / 存疑 / 过度工程）；
  `lines` = {total, core, tests, wiring, unrelated}（diff 总行数拆成净功能 / 测试 / 接线样板 / 夹带）；
  `baseline` = 最小替代基线行数；`delta_buys` = 差额买到了什么（一句话）。
  估不出的填 null 不许编。**批量分诊不写此字段**——性价比核算要读 diff 估基线，是深审产物。
- **published** = 审查意见已发布（/jason-post-review 回填）；**thanks** = 合并后感谢已发（同上）
- fixes/refs 以 cache 从 body 解析的为准；正文没写关联时才在行里补 `issues` 字段兜底

## 行动看板（sync 输出；全部派生，勿存）

| 桶 | 判据 | 下一步 |
|---|---|---|
| 🟢 待合并 | approve ∧ open ∧ sha 未动 | Jason 合并 |
| 🟠 候拍板 | pending-direction ∧ sha 未动 | Jason 方向决策 |
| 🔁 待重验 | 有 review ∧ head ≠ 审时 sha | /jason-review 重验 |
| 📮 待发布 | 有裁决（nits/rc/reject）∧ 未发出 | /jason-post-review |
| 🔍 待深审 | 已分诊 ∧ 无 review，按 priority 排序 | /jason-review |
| ⏳ 候作者 | 意见已发 ∧ sha 未动 | 等 push（push 后自动进待重验） |
| 🙏 待感谢 | merged ∧ thanks 空 | /jason-post-review 发感谢 |
| 🆕 未分诊 | open ∧ 不在台账 | 本 skill 批量分诊 |

## 默认流程（无参数）

1. 跑 `bash .claude/skills/jason-pr-triage/sync.sh`（首次自动全量，之后增量）——脚本直接打印看板。
2. 对未分诊清单批量分诊（下节）。**分诊前先 join issue 台账**：对每个 PR 的 fixes/refs，从
   `ledger.jsonl`/`groups.jsonl` 取 verdict + 根因组拼成 issueCtx 喂给子 agent
   （candid note 可进子 agent——本地 workflow 不外发）。
3. 主 agent 写 ledger（append；重分诊 jq 滤旧行再 append），补 `triaged_at`/`updated_at`。
4. 汇总给 Jason：各桶计数、新 P0/P1 逐条点名（含 priority_reason）、撞车/重复 PR 点名、backlog 数。

## 批量分诊执行方式

**> 10 条：必须用 Workflow 编排，子 agent 用 `model: 'opus'`**（与 issue 台账同规）；≤ 10 条 inline。
现成脚本 `.claude/skills/jason-pr-triage/triage-workflow.js`（勿每次重写）：

```
Workflow({ scriptPath: '<repo>/.claude/skills/jason-pr-triage/triage-workflow.js',
           args: { batches: [[{number,title,author,adds,dels,files,labels,issueCtx}, ...每批~8条], ...] } })
```

子 agent 自己拉 body（截 3000）+ 改动文件清单，schema 强制返回
`{triage: [{number, category, priority, priority_reason, modules, note}]}` —— 只返回数据，
绝不写 ledger、绝不操作 GitHub、**绝不碰 review 层**。归并与写文件永远在主 agent。

## 子命令

**`queue`** — 只跑 sync + 看板，不分诊（最轻入口，日常看一眼用）。

**`stats`** — 纯 jq 分析：open 按 category/priority 分布、作者维度（首次贡献者 open 数、top
贡献者）、age 分布、findings 遗留清单（packaged-into-thanks 且无 spawned:#N 的 = 邀请无人接）、
**性价比两表**（仅有 review.necessity 的行）：① grade × verdict 分布；② 差额榜
`(lines.total − baseline)` 降序，附 core/tests 占比与 delta_buys——回答"深审过的 PR 里多少是过度
工程、差额都买了什么"。

**`backfill N`** — 分诊最近活跃的 N 条未分诊 open PR（同批量流程）；merged/closed 历史懒回填。

**`<PR numbers…>`** — 只分诊/重分诊这些编号（inline，可读全部评论与完整 diff）。

## 三件套联动

- **/jason-review**（深审）：终裁落档时回写本台账该行的 review 层（滤旧行 append，triage 层
  字段原样保留；无行则连 category/priority 一并补）。
- **/jason-post-review**（发布）：发布后回填 `published`（审查意见）或 `thanks`（合并感谢）。
- **/jason-issue-triage**（issue 台账）：其"合并回写"步骤直接消费本 cache 的 fixes/refs 解析
  结果；反向，本 skill 分诊时 join 其 ledger/groups 定 priority。

## 红线

- 沿用 issue 台账全部红线：**candid 永不上 GitHub**；**绝不自动 merge/approve/comment/close**，
  一切对外动作只出草稿候 Jason；台账在 `~/.cc-switch-triage/` 不进公开仓库；cache 勿手改，
  坏了 `sync.sh --full` 重建。
- **review 层只由 /jason-review 写入**——批量分诊的浅判永不覆盖深审结论。
- **verdict 无 head_sha 锚点不得入库**；stale 与行动桶是派生态，一律不存。
- priority 是建议，Jason 拍板才是队列；本 skill 不据 priority 做任何自动对外动作。
