# -*- coding: utf-8 -*-
import os
import json
import sys
from pathlib import Path
import cv2
import numpy as np

def imread_u(path):
    with open(path, 'rb') as f:
        buf = np.frombuffer(f.read(), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)

ROOT = Path('D:/AI_dot/Codex/OAS_UI')
VARS_JSON = ROOT / 'OASX/assets/asset_snapshot_variables.json'
TEMPLATES_DIR = ROOT / 'OAS/tasks/AssetSnapshot/assets/templates'
CATALOG_JSON = TEMPLATES_DIR / 'template_catalog.json'
MATERIAL_DIR = TEMPLATES_DIR / 'material'
FULL_CELLS_MAT_DIR = TEMPLATES_DIR / 'full_cells/material'
TOP_DIR = TEMPLATES_DIR / 'top_resources'
FULL_CELLS_TOP_DIR = TEMPLATES_DIR / 'full_cells/top_resources'
QA_DIR = TEMPLATES_DIR / 'qa'
RAW_PAGES_DIR = QA_DIR / 'raw_pages'
DISABLED_TEMPLATE_DISPLAY_NAMES = {'神眷符咒_永恒'}

print('=======================================================')
print('   纳物库模板资产与清单只读校验 (Read-Only Validation)')
print('=======================================================')

errors = []
warnings = []

# 1. Check mapping
if not VARS_JSON.exists():
    errors.append(f'Mapping file missing: {VARS_JSON}')
    sys.exit(1)

with open(VARS_JSON, 'r', encoding='utf-8') as f:
    mapping = json.load(f)

print(f'1. 变量映射表检查: {len(mapping)} 条映射 (期望 73)')
if len(mapping) != 73:
    errors.append(f'Mapping length is {len(mapping)}, expected 73')

# 2. Check catalog
if not CATALOG_JSON.exists():
    errors.append(f'Catalog file missing: {CATALOG_JSON}')
    sys.exit(1)

with open(CATALOG_JSON, 'r', encoding='utf-8') as f:
    catalog = json.load(f)

print(f'2. 模板清单条目数: {len(catalog)} 条记录 (期望 72)')
if len(catalog) != 72:
    errors.append(f'Catalog length is {len(catalog)}, expected 72')

# 3. Check 1-to-1 correspondence
catalog_by_var = {}
catalog_by_disp = {}
catalog_paths = set()
full_cell_paths = set()

for idx, item in enumerate(catalog):
    disp = item.get('display_name')
    var = item.get('variable_name')
    path_str = item.get('template_path')
    full_path_str = item.get('full_cell_path')
    kind = item.get('kind')
    status = item.get('status')
    
    if not disp or not var or not path_str or not kind or not full_path_str:
        errors.append(f'Item {idx} missing required fields: {item}')
        continue
        
    if kind not in ['material', 'top_resource']:
        errors.append(f'Item {disp} invalid kind: {kind}')
        
    if status not in ['captured', 'fallback']:
        errors.append(f'Item {disp} invalid status: {status}')
        
    if var not in mapping.values():
        errors.append(f'Item {disp} variable {var} not in asset_snapshot_variables.json')
        
    if mapping.get(disp) != var:
        errors.append(f'Item {disp} variable mismatch: catalog has {var}, mapping has {mapping.get(disp)}')
        
    if var in catalog_by_var:
        errors.append(f'Duplicate variable in catalog: {var}')
    catalog_by_var[var] = item
    
    if disp in catalog_by_disp:
        errors.append(f'Duplicate display_name in catalog: {disp}')
    catalog_by_disp[disp] = item
    
    if path_str in catalog_paths:
        errors.append(f'Duplicate template_path in catalog: {path_str}')
    catalog_paths.add(path_str)
    
    if full_path_str in full_cell_paths:
        errors.append(f'Duplicate full_cell_path in catalog: {full_path_str}')
    full_cell_paths.add(full_path_str)

missing_in_catalog = set(mapping.keys()) - set(catalog_by_disp.keys()) - DISABLED_TEMPLATE_DISPLAY_NAMES
if missing_in_catalog:
    errors.append(f'Missing in catalog: {missing_in_catalog}')

# 4. Check disk files in both material/ and full_cells/
print('3. 磁盘物理文件存在性与尺寸校验:')
checked_primary = 0
checked_full = 0

for item in catalog:
    # Primary template
    rel_p = item['template_path']
    full_p = TEMPLATES_DIR / rel_p
    if not full_p.exists():
        errors.append(f'Template file not found: {full_p}')
        continue
    img = imread_u(str(full_p))
    if img is None:
        errors.append(f'Cannot decode image: {full_p}')
        continue
    h, w = img.shape[:2]
    checked_primary += 1
    
    expected_fname = f"{item['display_name']}.png"
    if full_p.name != expected_fname:
        errors.append(f'Primary filename mismatch: expected {expected_fname}, got {full_p.name}')
    
    # Full cell template
    rel_full_p = item['full_cell_path']
    full_cell_file = TEMPLATES_DIR / rel_full_p
    if not full_cell_file.exists():
        errors.append(f'Full cell file not found: {full_cell_file}')
        continue
    img_full = imread_u(str(full_cell_file))
    if img_full is None:
        errors.append(f'Cannot decode full cell image: {full_cell_file}')
        continue
    fh, fw = img_full.shape[:2]
    checked_full += 1
    
    if full_cell_file.name != expected_fname:
        errors.append(f'Full cell filename mismatch: expected {expected_fname}, got {full_cell_file.name}')
        
    if item['kind'] == 'material':
        if (w, h) != (95, 70):
            errors.append(f"Material {item['display_name']} size is {w}x{h}, expected 95x70")
        if (fw, fh) != (95, 95):
            errors.append(f"Full cell {item['display_name']} size is {fw}x{fh}, expected 95x95")
        if item.get('quantity_exclusion') != [40, 68, 54, 25]:
            errors.append(f"Material {item['display_name']} missing or invalid quantity_exclusion: {item.get('quantity_exclusion')}")
    elif item['kind'] == 'top_resource':
        if w < 30 or w > 60 or h < 30 or h > 60:
            errors.append(f"Top resource {item['display_name']} unexpected size {w}x{h}")

print(f'   成功读取并校验 {checked_primary} 个主模板文件，{checked_full} 个完整格子对照文件')

# 5. Check directory contents for extra files
top_files = set(os.listdir(TOP_DIR))
expected_top_files = {f"{item['display_name']}.png" for item in catalog if item['kind'] == 'top_resource'}
if top_files - expected_top_files:
    errors.append(f'Extra files in top_resources: {top_files - expected_top_files}')

mat_files = set(os.listdir(MATERIAL_DIR))
expected_mat_files = {f"{item['display_name']}.png" for item in catalog if item['kind'] == 'material'}
documented_variants = {'典藏礼券_选中.png'}
if mat_files - expected_mat_files - documented_variants:
    errors.append(f'Extra files in material: {mat_files - expected_mat_files - documented_variants}')

full_mat_files = set(os.listdir(FULL_CELLS_MAT_DIR))
if full_mat_files - expected_mat_files - documented_variants:
    errors.append(f'Extra files in full_cells/material: {full_mat_files - expected_mat_files - documented_variants}')

# 6. Status and coverage breakdown
captured = [i for i in catalog if i.get('status') == 'captured']
fallbacks = [i for i in catalog if i.get('status') == 'fallback']
print(f'4. 数据源覆盖统计:')
print(f'   - 实测截图裁切成功: {len(captured)} 项')
print(f'   - 官方资产补图兜底 (fallback): {len(fallbacks)} 项 (用户纳物库持有量为0)')
for fb in fallbacks:
    print(f"     * {fb['display_name']} ({fb['variable_name']}) - 标记: fallback")

# 7. Check QA images and raw pages
raw_pages = sorted(os.listdir(RAW_PAGES_DIR))
print(f'5. QA 资产检查:')
print(f'   - 原始全景截图页数: {len(raw_pages)} 页 ({raw_pages})')
print(f'   - 索引拼图: qa_templates_index.png 存在: {(QA_DIR / "qa_templates_index.png").exists()}')
print(f'   - 覆盖清单: qa_coverage_manifest.json 存在: {(QA_DIR / "qa_coverage_manifest.json").exists()}')

print('=======================================================')
if errors:
    print(f'FAILED: 发现 {len(errors)} 个错误!')
    for e in errors:
        print('  [ERROR]', e)
    sys.exit(1)
else:
    print(f'SUCCESS: {len(catalog)} 个模板校验通过，保留 {len(mapping)} 个接口字段。')
