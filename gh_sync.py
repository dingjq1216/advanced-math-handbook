# -*- coding: utf-8 -*-
"""
把当前工作区的改动，经 GitHub 官方 API 直接发布到远端仓库。

为什么需要它
   本机到 github.com:443（git 自己的传输通道）经常连不上，而 api.github.com
   一直正常。git push 走的正是前一条通道，所以一断就推不动。这个脚本绕开 git
   的传输层，改用 GitHub 的 Git Data API 直接建 blob / tree / commit，再移动
   分支指针，一次提交完成「本地工作区 → 远端仓库」的完整同步。

职责
    1. 用 git（纯本地操作，不联网）算出该发布的文件清单及其指纹
    2. 拉取远端分支当前的文件清单与指纹
    3. 只上传指纹有差异的文件，删除远端多余的文件，合成一个 commit
    4. 网络允许时，顺手用 git 把本地分支对齐到远端

用法
    改完书稿后在仓库目录运行：python gh_sync.py
    只想看看差异不提交：把入口的 dry_run 改成 True
"""
import base64
import json
import os
import subprocess
import urllib.error
import urllib.request

# ------------------------------------------------------------------
# 全局常量
# ------------------------------------------------------------------
API_ROOT = 'https://api.github.com'
API_VERSION = '2022-11-28'
TIMEOUT_SECONDS = 60
FILE_MODE = '100644'                    # 普通文件（非可执行）


# ------------------------------------------------------------------
# 通用工具
# ------------------------------------------------------------------
def run_git(args: list, cwd: str) -> str:
    """在指定仓库里执行一条 git 命令，返回标准输出（去掉首尾空白）。"""
    result = subprocess.run(['git'] + args, cwd=cwd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode('utf-8', 'replace').strip()
        raise RuntimeError(f"git {' '.join(args)} 执行失败：{stderr}")
    return result.stdout.decode('utf-8', 'replace').strip()


def get_token() -> str:
    """从 GitHub CLI 取当前登录令牌，避免把 token 写进源码。"""
    result = subprocess.run(['gh', 'auth', 'token'], capture_output=True)
    token = result.stdout.decode('utf-8', 'replace').strip()
    if result.returncode != 0 or not token:
        raise RuntimeError('取不到 GitHub 令牌，请先在终端执行：gh auth login')
    return token


def api_request(token: str, method: str, path: str, payload: dict = None) -> dict:
    """调用 GitHub REST API，返回解析后的 JSON。"""
    url = path if path.startswith('http') else f'{API_ROOT}{path}'
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header('Authorization', f'Bearer {token}')
    request.add_header('Accept', 'application/vnd.github+json')
    request.add_header('X-GitHub-Api-Version', API_VERSION)
    if body is not None:
        request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')
        raise RuntimeError(f'{method} {path} 失败（HTTP {error.code}）：{detail}') from error
    except urllib.error.URLError as error:
        raise RuntimeError(f'{method} {path} 连不上 GitHub API：{error.reason}') from error
    return json.loads(text) if text else {}


# ------------------------------------------------------------------
# 文件清单
# ------------------------------------------------------------------
def list_local_files(local_dir: str) -> dict:
    """列出该发布的本地文件，返回 {相对路径: blob 指纹}。

    先用 git add -A 让 .gitignore 生效（纯本地操作，不联网），
    再用 git hash-object 算出每个文件内容在 git 里的指纹——
    这个指纹与 GitHub 端的 blob sha 算法一致，可以直接比对，
    于是「没改过的文件」就不必重复上传。
    """
    run_git(['add', '-A'], local_dir)
    listing = run_git(['-c', 'core.quotePath=false', 'ls-files'], local_dir)
    files = {}
    for line in listing.splitlines():
        rel = line.strip()
        if rel:
            files[rel.replace('\\', '/')] = run_git(
                ['hash-object', '--path', rel, rel], local_dir)
    return files


def get_remote_head(token: str, repo: str, branch: str) -> str:
    """取远端分支当前指向的 commit sha。"""
    data = api_request(token, 'GET', f'/repos/{repo}/git/ref/heads/{branch}')
    return data['object']['sha']


def list_remote_files(token: str, repo: str, commit_sha: str) -> dict:
    """列出远端某次提交的整棵文件树，返回 {相对路径: blob 指纹}。"""
    commit = api_request(token, 'GET', f'/repos/{repo}/git/commits/{commit_sha}')
    tree = api_request(
        token, 'GET', f"/repos/{repo}/git/trees/{commit['tree']['sha']}?recursive=1")
    return {item['path']: item['sha']
            for item in tree.get('tree', []) if item['type'] == 'blob'}


def diff_files(local: dict, remote: dict) -> dict:
    """比较本地与远端，返回 {'新增': [...], '修改': [...], '删除': [...]}。"""
    return {
        '新增': sorted(p for p in local if p not in remote),
        '修改': sorted(p for p in local if p in remote and local[p] != remote[p]),
        '删除': sorted(p for p in remote if p not in local),
    }


def build_commit_message(changes: dict) -> str:
    """按改动内容自动生成中文提交信息。"""
    total = sum(len(v) for v in changes.values())
    parts = [f'{name} {len(items)} 个' for name, items in changes.items() if items]
    title = f'同步书稿：共 {total} 个文件（' + '、'.join(parts) + '）'
    lines = [title, '']
    for name, items in changes.items():
        if items:
            lines.append(f'{name}：' + '、'.join(items))
    return '\n'.join(lines)


# ------------------------------------------------------------------
# 发布
# ------------------------------------------------------------------
def create_blob(token: str, repo: str, file_path: str) -> str:
    """上传一个文件的内容，返回它的 blob 指纹。"""
    with open(file_path, 'rb') as handle:
        content = base64.b64encode(handle.read()).decode('ascii')
    blob = api_request(token, 'POST', f'/repos/{repo}/git/blobs',
                       {'content': content, 'encoding': 'base64'})
    return blob['sha']


def publish(token: str, repo: str, branch: str, local_dir: str,
            changes: dict, base_commit: str, message: str) -> str:
    """建 blob / tree / commit 并移动分支指针，返回新的 commit sha。"""
    entries = []
    for name in ('新增', '修改'):
        for rel in changes[name]:
            blob_sha = create_blob(token, repo, os.path.join(local_dir, rel))
            entries.append({'path': rel, 'mode': FILE_MODE,
                            'type': 'blob', 'sha': blob_sha})
            print(f'   ⬆️  已上传 {rel}')
    for rel in changes['删除']:
        # sha 传 null，GitHub 会把这个条目从新树里删掉
        entries.append({'path': rel, 'mode': FILE_MODE,
                        'type': 'blob', 'sha': None})
        print(f'   🗑️  已删除 {rel}')

    base_tree = api_request(
        token, 'GET', f'/repos/{repo}/git/commits/{base_commit}')['tree']['sha']
    tree = api_request(token, 'POST', f'/repos/{repo}/git/trees',
                       {'base_tree': base_tree, 'tree': entries})
    commit = api_request(token, 'POST', f'/repos/{repo}/git/commits',
                         {'message': message, 'tree': tree['sha'],
                          'parents': [base_commit]})
    api_request(token, 'PATCH', f'/repos/{repo}/git/refs/heads/{branch}',
                {'sha': commit['sha'], 'force': False})
    return commit['sha']


def align_local_repo(local_dir: str, branch: str) -> str:
    """网络允许时，用 git 把本地分支对齐到远端；连不上就跳过，不影响发布。"""
    try:
        run_git(['fetch', 'origin'], local_dir)
    except RuntimeError as error:
        return f'⏭️  跳过本地对齐（github.com 仍连不上）：{str(error).splitlines()[0][:80]}'

    local_sha = run_git(['rev-parse', 'HEAD'], local_dir)
    remote_sha = run_git(['rev-parse', f'origin/{branch}'], local_dir)
    if local_sha == remote_sha:
        return f'✅ 本地与远端已一致（{remote_sha[:8]}）'
    run_git(['reset', '--hard', f'origin/{branch}'], local_dir)
    return f'✅ 本地已对齐到远端（{remote_sha[:8]}）'


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------
def main(config: dict) -> None:
    """按 config 执行一次完整同步。"""
    repo, branch = config['repo'], config['branch']
    local_dir = config['local_dir']

    print('=' * 60)
    print(f'📦 目标仓库：{repo}（分支 {branch}）')
    print(f'📂 本地目录：{local_dir}')
    print('=' * 60)

    print('🔍 正在清点本地文件……')
    local_files = list_local_files(local_dir)
    print(f'   本地该发布的文件：{len(local_files)} 个')

    token = get_token()
    print('🔍 正在拉取远端清单……')
    base_commit = get_remote_head(token, repo, branch)
    remote_files = list_remote_files(token, repo, base_commit)
    print(f'   远端已有文件：{len(remote_files)} 个（{base_commit[:8]}）')

    changes = diff_files(local_files, remote_files)
    print('-' * 60)
    for name, items in changes.items():
        print(f'   {name}：{len(items)} 个' + (f' → {"、".join(items[:8])}'
                                             + (' ……' if len(items) > 8 else '')
                                             if items else ''))

    if config['dry_run']:
        print('=' * 60)
        print('🧪 dry_run 已开启，只看差异，不提交。')
        return

    if sum(len(v) for v in changes.values()) == 0:
        print('=' * 60)
        print('🎉 远端已是最新，无需提交。')
        return

    print('-' * 60)
    message = config['commit_message'] or build_commit_message(changes)
    print(f'🚀 正在提交：{message.splitlines()[0]}')
    new_commit = publish(token, repo, branch, local_dir,
                         changes, base_commit, message)
    print(f'✅ 提交成功：{new_commit[:8]}')
    print(f'   https://github.com/{repo}/commit/{new_commit}')

    if config['try_git_align']:
        print('-' * 60)
        print('🔄 尝试用 git 对齐本地仓库……')
        print(align_local_repo(local_dir, config['branch']))
    print('=' * 60)
    print('🎉 完成！')


# ==================================================================
# 主程序入口（唯一执行点）
# ==================================================================
if __name__ == '__main__':
    # ======================== 集中配置区：改这里就够了 ========================
    config = {
        'repo': 'dingjq1216/advanced-math-handbook',
        'branch': 'main',
        'local_dir': r'd:\理论研究学习\数学基础',
        'commit_message': '',        # 留空则按改动自动生成中文提交信息
        'dry_run': False,            # True 只看差异，不提交
        'try_git_align': True,       # 提交后尝试把本地分支对齐到远端
    }
    main(config=config)
