---
description: Rebuild the repobrain project knowledge base after significant changes. / 在重要改动后重建 repobrain 项目知识库。
allowed-tools: ["Bash"]
---

Run the RepoBrain CLI for the current workspace.

通过 RepoBrain CLI 刷新当前工作区知识库。

Use Bash:

```bash
rb-refresh --workspace "$PWD"
```

使用 Bash：

```bash
rb-refresh --workspace "$PWD"
```

If $ARGUMENTS contains `quick`, add `--quick`. Quick mode compares only committed
changes, requires a clean worktree, and lets RepoBrain's ImpactPlanner plus an
independent Verifier update only affected Agent groups. It never falls back to
a full refresh. If $ARGUMENTS contains `failed-only`, add `--failed-only` to
resume the failed/pending groups for the same target commit.

如果 $ARGUMENTS 包含 `quick`，追加 `--quick`。quick 只比较已提交变更，要求工作区
干净，由 RepoBrain ImpactPlanner 与独立 Verifier 只更新受影响 Agent 分组，且绝不
自动降级为全量刷新。如果 $ARGUMENTS 包含 `failed-only`，追加 `--failed-only`，
续跑同一目标提交中失败或待处理的分组。

If `rb-refresh` is not found, tell the user the engine CLI is not installed and suggest:

如果找不到 `rb-refresh`，说明 engine CLI 尚未安装，建议用户运行：

```bash
pipx install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"
```

Report progress concisely; full refresh can take several minutes.

简洁汇报进度；完整 refresh 可能需要几分钟。
