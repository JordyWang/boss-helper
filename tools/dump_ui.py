"""dump 当前手机界面,保存 hierarchy.xml + 截图,用于校准 selectors.py。"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2

from boss.config import load_config


def dump(config_path: str = "config.yaml") -> str:
    cfg = load_config(config_path)
    d = u2.connect(cfg.serial or None)

    os.makedirs("logs/dump", exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    xml_path = os.path.join("logs/dump", f"hierarchy_{stamp}.xml")
    png_path = os.path.join("logs/dump", f"screen_{stamp}.png")

    xml = d.dump_hierarchy()
    with open(xml_path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    d.screenshot(png_path)

    print(f"已保存层级: {xml_path}")
    print(f"已保存截图: {png_path}")
    print("\n在 XML 中搜索目标控件的 resource-id / text / content-desc,")
    print("回填到 boss/selectors.py 对应位置即可。")
    return xml_path


if __name__ == "__main__":
    dump()
