---
name: jason-post-review
description: Turn a PR review verdict (from the current session or the memory ledger) into a publishable GitHub review comment, show the draft for confirmation, then post it to the PR via gh. Never posts without explicit confirmation.
argument-hint: "[PR 编号] — 默认：当前会话刚完成审查的那个 PR；历史裁决从记忆台账取"
---

# Post Review — 把审查结论发布到 PR

审查结论的 SSOT 是**当前会话的审查过程**，其次是记忆台账
`~/.claude/projects/-Users-jasonyoung-Code-cc-switch/memory/project_pr<N>_*review*.md`。
本 skill 只做「取数 → 成稿 → 确认 → 发布」，**不做审查**——没有现成结论时提示先跑
`/jason-review <N>`，不要临时拼凑。

## 默认流程

1. **定位 PR**：参数给了编号用参数；否则用当前会话刚审查的 PR；都没有就问。
2. **取结论**：优先当前会话上下文；会话里没有 → 读记忆台账对应文件。
   ⚠️ 台账是内部候审记录（含 candid 备注、首轮/二轮过程、记忆 slug 链接），
   **只作素材，严禁整段照搬进评论**。
3. **新鲜度检查**：`gh pr view <N> --json state,headRefOid,title`
   - 已 merged/closed → 报告并停。
   - head 与审查时的 commit 不一致 → 列出新增 commit，先向用户确认结论是否仍适用。
4. **成稿**（规范见下节），完整草稿放码块展示；动作默认就是 comment 态
   review，无需再问——只有用户明示 request-changes / approve 时才说明改用的动作。
5. **等明确确认后**才发布。用户在本次调用里明确说了"直接发"可跳过展示步骤。
6. **发布**：正文写入 scratchpad 文件（避免 shell 引号问题），然后
   `gh pr review <N> --comment --body-file <file>`（默认；明示升级时换
   `--request-changes|--approve`）。
   自己名下的 PR 不能提交任何状态的 review → 自动降级 `gh pr comment`
   （此时不计贡献图，无解）。
7. **收尾**：报告评论 URL；若该 PR 有记忆台账文件，追加一行
   `已发布 <动作> (<日期>, <URL>)`；同时回填 PR 台账
   `~/.cc-switch-triage/pr-ledger.jsonl`：合并前的审查意见 → `published`
   字段，合并后的感谢评论 → `thanks` 字段（均记 url+date，详见 `/jason-pr-triage`）。

## 成稿规范（语言随 PR，Jason 的口吻）

- **语言**：跟随 PR 作者的语言。判定信号按优先级：作者在 PR / 关联 issue 里的
  **自由文本评论** > PR 描述里模板之外的自由文本 > 提交信息。⚠️ 本仓 PR/issue
  模板是中英双语，照模板填出来的英文**不算信号**。判定不出来时默认英文。
  草稿展示时说明一句判定依据（如"作者评论是中文 → 中文成稿"）。
- **结构**：1–2 句经核实的正面评价开头（不空捧）→ 按严重度列问题
  `[P1] / [P2] / nit` → 结尾说清"修掉哪些就能合并" + 愿意快速复审。
- **每条问题三件套**：论断 → 证据（文件/行号/上游链接）→ 最小修法
  （几行内的直接给代码片段）。
- **链接钉死到审查时的 head SHA**（`blob/<sha>/path#L10-L20`），不用分支名——分支会动。
- **范围纪律**：超出 PR 范围的深修（如接管层重构）→ 建议开 follow-up issue，
  别让作者误以为要在本 PR 里做大手术。
- **动作映射**：**默认一律 comment 态 review**（`gh pr review --comment`），
  与裁决严重度无关——不打 "changes requested" 红标、不阻塞合并，且计入
  GitHub 贡献图（`gh pr comment` 的 issue comment 不计，勿混用）。阻断项的
  严重度在正文用 `[P1]/[P2]` 和"修掉哪些就能合并"表达，不靠 review 状态。
  request-changes / approve 仅在 Jason 明确要求时使用。

## 红线

- 🔴 **只写 CONFIRMED 的发现**。每个文件行号、数字、上游引用都必须是本次会话或
  台账里实际验证过的——概括句是高危区，不发明数量、不写未核实的断言。
- 🔴 **内部内容不外流**：candid 备注、记忆 slug、审查轮次过程、与其他 PR 的
  内部裁决对比，一律不进评论。
- 🔴 **不带 AI 署名**：无 "Generated with" 尾注、无 session 链接（与提交信息规则同源）。
- 🔴 **未经确认不发布**（唯一例外见流程第 5 步）。发布是外发动作，措辞就是产品。

## Advanced（仅在用户要求时）

- **行级评论**：`gh api repos/{owner}/{repo}/pulls/<N>/reviews` 带 `comments[]`
  （path + line + body）把各条钉到具体行，正文只留总评。
- **中英双语版**：中文对照追加在英文之后，用 `---` 分隔。
- **修订版复核评论**：作者推了修复后的追评（"Re-checked <sha>: …"），同样走
  取数→成稿→确认流程，动作同样默认 comment 态 review（approve 仍需明示）。
