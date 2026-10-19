#!/usr/bin/env bash
# sync_skills.sh — 全局 skills（权威副本）<-> EmbedSkills 仓库镜像，双向同步与漂移检查
#
# ---------------------------------------------------------------------------
# 架构（2026-09-30 起）
#   * 唯一权威副本 = 全局 ~/.workbuddy/skills/。所有编辑都在全局做；各工程**直接**
#     使用全局 skills，不再在工程内维护 .workbuddy/skills/ 镜像。
#   * 本仓库 EmbedSkills/ 是全局 skills 的**版本化镜像**，一个仓库覆盖所有工程，
#     便于随 git 分发、审阅与换机恢复。
#
# 纳管范围 = **自动发现**：两侧各自的顶层子目录（= 一个 skill）+ 顶层普通文件
#   （如能力表 STM32_skills_能力表.md），仅排除下面的 DENYLIST，再取并集。
#   ⚠️ 刻意不做硬编码白名单——历史版本的固定清单会随 skill 改名/合并而过期，导致
#   静默漏同步（见 README「为什么自动发现」）。
#   ⚠️ 也刻意**两侧都扫**：只扫全局时 `--restore` 补不上"全局缺、镜像有"的目录
#   （2026-10-19 实测：全局被回退少了 15 个 skill，restore 仍报漂移，只能手动 cp）。
#
# 用法（Git Bash / WSL / Linux）
#   ./sync_skills.sh             全局 -> EmbedSkills（默认，刷新镜像）
#   ./sync_skills.sh --check     只报告漂移，不改动（0=一致, 1=有漂移）
#   ./sync_skills.sh --restore   EmbedSkills -> 全局（换机 / 灾后恢复）
#   ./sync_skills.sh --prune     清理镜像侧冗余文件（全局已删的残留）
#   ./sync_skills.sh --list      打印本次纳管清单
#
# 退出码：0 = 成功 / 无漂移；1 = 有漂移或出错。
# ---------------------------------------------------------------------------

set -uo pipefail

GLOBAL_DIR="${HOME}/.workbuddy/skills"
MIRROR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 不纳管的顶层条目（仓库自身文件 / VCS / 工程元数据）
DENYLIST=( "README.md" ".git" ".gitignore" ".workbuddy" ".github" "sync_skills.sh" "lint_skills.py" )

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -d "${GLOBAL_DIR}" ] || die "全局 skills 目录不存在: ${GLOBAL_DIR}"
[ -d "${MIRROR_DIR}" ] || die "镜像目录不存在: ${MIRROR_DIR}"

is_denied() {
  local name="$1" d
  for d in "${DENYLIST[@]}"; do
    [ "${name}" = "${d}" ] && return 0
  done
  return 1
}

# ---- 自动发现纳管清单 -------------------------------------------------------
# 顶层子目录 = skill；顶层普通文件 = 附带资料（能力表等）。
# ⚠️ 两侧都发现再取并集：只看全局会让 `--restore` 永远补不上"全局缺、镜像有"的
# 目录（2026-10-19 实测：全局少 15 个 skill，restore 仍漂移，只能手动 cp）。
# 去重刻意用 bash 的 case 判重，不用 `sort -u`（本机 System32\sort.exe 会遮蔽它并静默返回空）。
MANAGED_SKILLS=()
while IFS= read -r d; do
  n="${d##*/}"
  is_denied "${n}" && continue
  case " ${MANAGED_SKILLS[*]-} " in *" ${n} "*) continue ;; esac
  MANAGED_SKILLS+=( "${n}" )
done < <(
  { find "${GLOBAL_DIR}" -mindepth 1 -maxdepth 1 -type d
    find "${MIRROR_DIR}" -mindepth 1 -maxdepth 1 -type d ; } | sort
)

MANAGED_FILES=()
while IFS= read -r f; do
  n="${f##*/}"
  is_denied "${n}" && continue
  case " ${MANAGED_FILES[*]-} " in *" ${n} "*) continue ;; esac
  MANAGED_FILES+=( "${n}" )
done < <(
  { find "${GLOBAL_DIR}" -mindepth 1 -maxdepth 1 -type f ! -name '.*'
    find "${MIRROR_DIR}" -mindepth 1 -maxdepth 1 -type f ! -name '.*' ; } | sort
)

MODE="sync"
case "${1:-}" in
  ""|--sync)   MODE="sync" ;;
  --check)     MODE="check" ;;
  --restore)   MODE="restore" ;;
  --prune)     MODE="prune" ;;
  --list)      MODE="list" ;;
  -h|--help)
    sed -n '2,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
  *) die "未知参数: $1（用 --help 看用法）" ;;
esac

list_managed() {
  printf '纳管 skill（%d 个，自动发现）:\n' "${#MANAGED_SKILLS[@]}"
  printf '  - %s\n' "${MANAGED_SKILLS[@]}"
  printf '纳管文件:\n'
  if [ "${#MANAGED_FILES[@]}" -eq 0 ]; then
    printf '  （无）\n'
  else
    printf '  - %s\n' "${MANAGED_FILES[@]}"
  fi
}

if [ "${MODE}" = "list" ]; then
  printf '全局（权威）: %s\n' "${GLOBAL_DIR}"
  printf '镜像（仓库）: %s\n' "${MIRROR_DIR}"
  list_managed
  exit 0
fi

# ---- 漂移检测 ---------------------------------------------------------------
# 返回 0 = 一致；1 = 有差异（逐项 diff，输出差异摘要）。
check_drift() {
  local drift=0 item src dst
  for item in "${MANAGED_SKILLS[@]}"; do
    src="${GLOBAL_DIR}/${item}"
    dst="${MIRROR_DIR}/${item}"
    if [ ! -d "${src}" ]; then
      printf '  [仅镜像存在→需 restore] %s\n' "${item}"; drift=1; continue
    fi
    if [ ! -d "${dst}" ]; then
      printf '  [仅全局存在→需 sync] %s\n' "${item}"; drift=1; continue
    fi
    if ! diff -r -q "${src}" "${dst}" >/dev/null 2>&1; then
      printf '  [内容漂移] %s\n' "${item}"
      diff -r -q "${src}" "${dst}" 2>/dev/null | sed 's/^/      /'
      drift=1
    fi
  done
  for item in "${MANAGED_FILES[@]}"; do
    src="${GLOBAL_DIR}/${item}"
    dst="${MIRROR_DIR}/${item}"
    if [ ! -f "${src}" ]; then
      printf '  [仅镜像存在→需 restore] %s\n' "${item}"; drift=1; continue
    fi
    if [ ! -f "${dst}" ]; then
      printf '  [仅全局存在→需 sync] %s\n' "${item}"; drift=1; continue
    fi
    cmp -s "${src}" "${dst}" || { printf '  [内容漂移] %s\n' "${item}"; drift=1; }
  done
  return "${drift}"
}

if [ "${MODE}" = "check" ]; then
  printf '== 漂移检查（%s -> %s）==\n' "${GLOBAL_DIR}" "${MIRROR_DIR}"
  if check_drift; then
    printf 'RESULT: IDENTICAL（镜像与全局权威副本一致，纳管 %d skill + %d 文件）\n' \
      "${#MANAGED_SKILLS[@]}" "${#MANAGED_FILES[@]}"
    exit 0
  fi
  printf 'RESULT: DRIFT（[仅全局存在] 跑 ./sync_skills.sh；[仅镜像存在] 跑 ./sync_skills.sh --restore）\n'
  exit 1
fi

# ---- 同步 -------------------------------------------------------------------
# SRC -> DST，**覆盖式合并**（不预删整目录）。
# 理由：沙箱对脚本内批量递归删除有中断行为，且「源是超集」时根本不需要删。
# 若源侧删过文件而镜像侧残留，--check 会报漂移，用 --prune 逐个清理（少量 rm -f）。
mirror_to() {
  local from="$1" to="$2" item
  for item in "${MANAGED_SKILLS[@]}"; do
    if [ ! -d "${from}/${item}" ]; then
      printf '  [跳过-源缺失] %s\n' "${item}"
      continue
    fi
    mkdir -p "${to}/${item}"
    cp -rf "${from}/${item}/." "${to}/${item}/" || die "拷贝失败: ${item}"
    printf '  [已同步] %s\n' "${item}"
  done
  for item in "${MANAGED_FILES[@]}"; do
    [ -f "${from}/${item}" ] || { printf '  [跳过-源缺失] %s\n' "${item}"; continue; }
    cp -f "${from}/${item}" "${to}/${item}" || die "拷贝失败: ${item}"
    printf '  [已同步] %s\n' "${item}"
  done
}

# 清理镜像侧存在、源侧已不存在的残留文件（逐个 rm -f，避免批量递归删除）。
# ⚠️ 必须**遍历镜像侧**再回查源侧；遍历源侧会永远找不到"只在镜像里的残留"（旧版 bug）。
prune_extras() {
  local from="$1" to="$2" item f d rel n=0
  for item in "${MANAGED_SKILLS[@]}"; do
    [ -d "${to}/${item}" ] || continue
    while IFS= read -r f; do
      [ -n "${f}" ] || continue
      rel="${f#${to}/${item}/}"
      if [ ! -e "${from}/${item}/${rel}" ]; then
        rm -f "${f}" && printf '  [已清理] %s/%s\n' "${item}" "${rel}"
        n=$((n + 1))
      fi
    done < <(cd "${to}/${item}" && find . -type f | sed "s|^\./|${to}/${item}/|")
    # 清理因文件删除而变空的镜像侧目录（自底向上，静默失败即可）
    while IFS= read -r d; do
      [ -n "${d}" ] || continue
      rmdir "${d}" 2>/dev/null
    done < <(cd "${to}/${item}" && find . -mindepth 1 -type d | sort -r | sed "s|^\./|${to}/${item}/|")
  done
  printf '  （共清理残留文件 %d 个）\n' "${n}"
}

if [ "${MODE}" = "sync" ] || [ "${MODE}" = "prune" ]; then
  if [ "${MODE}" = "prune" ]; then
    printf '== 清理镜像侧残留（全局已删除的文件）==\n'
    prune_extras "${GLOBAL_DIR}" "${MIRROR_DIR}"
  fi
  printf '== 全局 -> EmbedSkills 镜像（权威刷新）==\n'
  mirror_to "${GLOBAL_DIR}" "${MIRROR_DIR}"
  printf '== 校验 ==\n'
  if check_drift; then
    printf 'RESULT: OK（EmbedSkills 已与全局权威副本对齐）\n'
    exit 0
  fi
  printf 'RESULT: 同步后仍存在漂移（多为镜像侧残留文件）；跑 --prune 清理后重试\n'
  exit 1
fi

if [ "${MODE}" = "restore" ]; then
  printf '== EmbedSkills 镜像 -> 全局（灾后恢复）==\n'
  printf '⚠️  将覆盖全局 %s 下的纳管 skill，确认这是你要的（Ctrl-C 中止）\n' "${GLOBAL_DIR}"
  sleep 3
  mirror_to "${MIRROR_DIR}" "${GLOBAL_DIR}"
  printf '== 校验 ==\n'
  if check_drift; then
    printf 'RESULT: OK（全局已由 EmbedSkills 镜像恢复）\n'
    exit 0
  fi
  printf 'RESULT: 恢复后仍存在漂移，请检查\n'
  exit 1
fi
