"""dump 当前手机界面,保存 hierarchy.xml + 截图,用于校准 selectors.py。"""
from __future__ import annotations

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boss.config import ConfigError, load_config
from boss.artifacts import RunArtifacts


def dump(
    config_path: str = "config.yaml", artifacts: Optional[RunArtifacts] = None
) -> str:
    cfg = load_config(config_path)
    owned_artifacts = artifacts is None
    if artifacts is None:
        artifacts = RunArtifacts.create()
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        if owned_artifacts:
            artifacts.close()
        raise RuntimeError(
            "缺少 uiautomator2 依赖，请先执行: pip install -r requirements.txt"
        ) from exc
    try:
        d = u2.connect(cfg.serial or None)
        xml_path = artifacts.save_dump(d, "dump.xml")
        png_path = artifacts.save_screenshot(d, "screenshot.png")

        print(f"已保存层级: {xml_path}")
        print(f"已保存截图: {png_path}")
        print("\n在 XML 中搜索目标控件的 resource-id / text / content-desc,")
        print("回填到 boss/selectors.py 对应位置即可。")
        return xml_path
    finally:
        if owned_artifacts:
            artifacts.close()


if __name__ == "__main__":
    try:
        dump()
    except (ConfigError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(2)
