#!/usr/bin/env python3
"""用人工审定词表补齐 MULLER2022 拓扑名称的中文目录。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pygplates

from build_runtime_regions import TOPOLOGY_PATHS


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "Data/processed/gplates/muller2022"
CATALOG_PATH = ROOT / "Assets/Resources/EarthRegionNamesZhCn.json"
MODEL_REFERENCE = "https://doi.org/10.5194/se-13-1127-2022"
TERM_REFERENCE = "https://www.termonline.cn/"

# 专名优先采用已有地名/地学通译；无稳定汉译的模型内部专名采用审慎音译。
GLOSSARY = {
    "Arequipa-Antofalla": "阿雷基帕—安托法亚",
    "Cache Creek/Mezcalera": "卡什克里克／梅斯卡莱拉",
    "Corsica-Sardinia-Calabria": "科西嘉—撒丁—卡拉布里亚",
    "Gamilaroi-Calliope": "加米拉罗伊—卡利俄珀",
    "Ganderia-West Avalonia": "甘德里亚—西阿瓦隆尼亚",
    "Ganderia-Avalonia": "甘德里亚—阿瓦隆尼亚",
    "Izu Bonin Mariana": "伊豆—小笠原—马里亚纳",
    "Juan Fernandez": "胡安·费尔南德斯",
    "Juan de Fuca": "胡安·德富卡",
    "Kohistan-Ladakh": "科希斯坦—拉达克",
    "Laurentia-Amazonia": "劳伦大陆—亚马孙陆块",
    "Lizard/Giessen": "利泽德／吉森",
    "Mazar-Kangxiwar": "麻扎—康西瓦",
    "Melanesia/Solomon": "美拉尼西亚／所罗门",
    "Menderes-Taurides": "门德雷斯—托罗斯",
    "Menderes-Tauridus": "门德雷斯—托罗斯",
    "Mongol-Okhotsk": "蒙古—鄂霍次克",
    "Rayner-Ruker": "雷纳—鲁克尔",
    "Stikinia/Slide Mountain": "斯提金尼亚／斯莱德山",
    "Yukon-Tanana": "育空—塔纳纳",
    "Carboniferous BAB north of NCB": "石炭纪华北地块以北弧后盆地",
    "Capricorn Plate (Kremeer et al 2003 AT)": "摩羯板块",
    "NeoTethys based on Ana's model MS12": "新特提斯洋（Ana模型）",
    "Mirovoi Ocean subductin under Siberia-Baltica": "俯冲于西伯利亚—波罗的卡之下的米洛维洋板块",
    "Ocean Plate subducting under SM and WES": "俯冲于SM与WES之下的洋板块",
    "North flank of BAB near Coral Sea": "珊瑚海附近弧后盆地北翼",
    "South flank of BAB near Coral Sea": "珊瑚海附近弧后盆地南翼",
    "Western half of South Loyalty Basin": "南洛亚蒂盆地西半部",
    "North and Central Sulawesi": "苏拉威西北部与中部",
    "North Slope Microplate of AACM": "AACM北坡微板块",
    "East Siberia Microplate of AACM": "AACM东部西伯利亚微板块",
    "Northern South Fiji Basin": "南斐济盆地北部",
    "Vancouver Plate (becomes Juan de Fuca)": "温哥华板块（演变为胡安·德富卡板块）",
    "Arctic Alaska/Chukotka Pale": "古北极阿拉斯加／楚科奇板块",
    "Lizard/GiessenOcean": "利泽德／吉森洋",
    "N Phil Basin": "北菲律宾盆地", "S Phil Basin": "南菲律宾盆地",
    "NLoyaltyBasinSth": "南洛亚蒂盆地", "NorthLoyaltyBasin": "北洛亚蒂盆地",
    "NthLoyaltyBasinSth": "南洛亚蒂盆地", "NthLoyaltySth": "南洛亚蒂地区",
    "Nan bab oceanic plate": "NAN弧后盆地洋板块",
    "NewBritain": "新不列颠板块",
    "Nfld_Early_ExhumedMantle": "纽芬兰早期出露地幔区",
    "Northen Rheic Plate": "北瑞克洋板块",
    "Northern indian ocean plate": "北印度洋板块",
    "Oceanic plate?": "洋板块？",
    "Southeast Sulawesi": "苏拉威西东南部板块",
    "Western meso Tethys (Semail)": "中特提斯洋西部（塞迈勒）",
    "WesternDinaride Plate": "西迪纳里德板块",
    "Woyla Back-arc": "沃伊拉弧后盆地",
    "kara": "喀拉板块", "kazak": "哈萨克板块",
    "East Scotia Sea SZ (2010)": "东斯科舍海板块",
    "Kohistan-Ladakh NORTH back-arc": "科希斯坦—拉达克北部弧后盆地",
    "Mazar-Kangxiwar BAB": "麻扎—康西瓦弧后盆地",
    "Ocean Plate subducting under Australia-TOAST": "俯冲于澳大利亚—TOAST之下的洋板块",
    "Ocean plate subducting under Kalahari-TOAST-Antarctica": "俯冲于卡拉哈里—TOAST—南极洲之下的洋板块",
    "PAC 79.1-77.2": "太平洋板块", "S.China Plate": "华南板块",
    "Subduction under COAB": "COAB之下的俯冲板块",
    "Afif-Abas": "阿菲夫—阿巴斯",
    "Australia-Antarctica": "澳大利亚—南极洲",
    "Australian-Antarctica": "澳大利亚—南极洲",
    "Australia-India": "澳大利亚—印度",
    "India-Australia": "印度—澳大利亚",
    "India-South China": "印度—华南",
    "Cimmerian-Neotethys": "辛梅利亚—新特提斯",
    "Congo-Azania": "刚果—阿扎尼亚",
    "Congo-SF": "刚果—圣弗朗西斯科",
    "Congo-SM": "刚果—撒哈拉变质克拉通",
    "Qaidam-Qilian": "柴达木—祁连",
    "Lut-Kunlun": "卢特—昆仑",
    "Sonora Mojave": "索诺拉—莫哈维",
    "Arctic Alaska/Chukotka": "北极阿拉斯加／楚科奇",
    "Sao Francisco": "圣弗朗西斯科",
    "South China": "华南",
    "North China": "华北",
    "North America": "北美",
    "South America": "南美",
    "East Antarctica": "东南极洲",
    "West Antarctica": "西南极洲",
    "New Britain": "新不列颠",
    "Proto South China Sea": "原始南海",
    "Mirovoi Ocean": "米洛维洋",
    "Neo Tethys": "新特提斯洋",
    "Meso Tethys": "中特提斯洋",
    "Paleotethys": "古特提斯洋",
    "Neotethys": "新特提斯洋",
    "NeoTethys": "新特提斯洋",
    "Iapetus": "伊阿珀托斯",
    "Gondwanna": "冈瓦纳大陆",
    "Gondwana": "冈瓦纳大陆",
    "Laurentia": "劳伦大陆",
    "Laurussia": "劳亚俄罗斯大陆",
    "Laurasia": "劳亚大陆",
    "Rodinia": "罗迪尼亚大陆",
    "Pangea": "盘古大陆",
    "Amazonia": "亚马孙陆块",
    "Kazakhstania": "哈萨克斯坦尼亚",
    "Kazakstania": "哈萨克斯坦尼亚",
    "Avalonia": "阿瓦隆尼亚",
    "Carolinia": "卡罗利尼亚",
    "Borborema": "博博雷马",
    "Cuyania": "库亚尼亚",
    "Azania": "阿扎尼亚",
    "Pampia": "潘皮亚",
    "Sibumasu": "西布马苏",
    "Sundaland": "巽他陆架",
    "Farallon": "法拉隆",
    "Izanagi": "伊邪那岐",
    "Kula": "库拉",
    "Phoenix": "凤凰",
    "Pacific": "太平洋",
    "Nazca": "纳斯卡",
    "Caribbean": "加勒比",
    "Caroline": "加罗林",
    "Bellingshausen": "别林斯高晋",
    "Hikurangi": "希库朗伊",
    "Galapagos": "加拉帕戈斯",
    "Vancouver": "温哥华",
    "Manihiki": "马尼希基",
    "Magallanes": "麦哲伦",
    "Mathematician": "数学家",
    "Bauer": "鲍尔",
    "Challenger": "挑战者",
    "Catequil": "卡特基尔",
    "Rivera": "里维拉",
    "Porcupine": "豪猪",
    "Scotia": "斯科舍",
    "Sandwich": "桑威奇",
    "Capricorn": "摩羯",
    "Tonga": "汤加",
    "Cocos": "科科斯",
    "Africa": "非洲",
    "Australia": "澳大利亚",
    "Australian": "澳大利亚",
    "Antarctica": "南极洲",
    "Eurasia": "欧亚",
    "Greenland": "格陵兰",
    "Madagascar": "马达加斯加",
    "Patagonia": "巴塔哥尼亚",
    "Arabia": "阿拉伯",
    "India": "印度",
    "Indian": "印度",
    "Philippine": "菲律宾",
    "Philippines": "菲律宾",
    "Africa": "非洲",
    "Siberia": "西伯利亚",
    "Kalahari": "卡拉哈里",
    "Congo": "刚果",
    "Sahara": "撒哈拉",
    "Hoggar": "阿哈加尔",
    "Amuria": "阿穆尔",
    "Angara": "安加拉",
    "Annamia": "安南",
    "Afif": "阿菲夫",
    "Aluk": "阿卢克",
    "Alexander": "亚历山大",
    "Kohistan": "科希斯坦",
    "Lhasa": "拉萨",
    "Lut": "卢特",
    "Kunlun": "昆仑",
    "Qaidam": "柴达木",
    "Qilian": "祁连",
    "Qinling": "秦岭",
    "Tianshan": "天山",
    "Tarim": "塔里木",
    "Alxa": "阿拉善",
    "Erguna": "额尔古纳",
    "Kamchatka": "堪察加",
    "Kara": "喀拉",
    "Oman": "阿曼",
    "Hijaz": "汉志",
    "Palawan": "巴拉望",
    "Celebes": "苏拉威西",
    "Molucca": "马鲁古",
    "Solomon": "所罗门",
    "Tasmania": "塔斯马尼亚",
    "Taimyr": "泰梅尔",
    "Mawson": "莫森",
    "Weddell": "威德尔",
    "Norfolk": "诺福克",
    "Sumatra": "苏门答腊",
    "Sulawesi": "苏拉威西",
    "Yucatan": "尤卡坦",
    "Yucan": "尤卡坦",
    "Florida": "佛罗里达",
    "Iberia": "伊比利亚",
    "Adria": "阿德里亚",
    "Dinaride": "迪纳里德",
    "Diniride": "迪纳里德",
    "Vardar": "瓦尔达尔",
    "Kirshehir": "克尔谢希尔",
    "Menderes": "门德雷斯",
    "Taurides": "托罗斯",
    "Tauridus": "托罗斯",
    "Variscian": "华力西",
    "Penobscot": "佩诺布斯科特",
    "Popelogan": "波普洛根",
    "Ganderia": "甘德里亚",
    "Gravina": "格拉维纳",
    "Chortis": "乔蒂斯",
    "Semitau": "谢米陶",
    "Sepik": "塞皮克",
    "Sukhothai": "素可泰",
    "Woyla": "沃伊拉",
    "Timan": "季曼",
    "Alcapia": "阿尔卡皮亚", "Backarc": "弧后", "Big": "大型",
    "Banda": "班达", "Baltica": "波罗的卡", "Chazca": "查斯卡",
    "Chu Yili": "楚—伊犁", "Coral": "珊瑚", "Emo": "埃莫",
    "Ethiopian": "埃塞俄比亚", "Fiji": "斐济", "Final": "最终",
    "Indochina": "印度支那", "Iforus": "伊福鲁斯", "Japan": "日本",
    "Junction": "汇合", "Kabaliye": "卡巴利耶", "Kabalye": "卡巴利耶",
    "Kabalyeh": "卡巴利耶", "Klamath": "克拉马斯", "Latea": "拉蒂亚",
    "Loyalty": "洛亚蒂", "Magnitogorsk": "马格尼托哥尔斯克",
    "Mariana": "马里亚纳", "Melanesian": "美拉尼西亚", "Midyan": "米甸",
    "Mirovoi": "米洛维", "Moroccan": "摩洛哥", "Norfold": "诺福克",
    "Parana": "巴拉那", "Rheic": "瑞克", "Rennell": "伦内尔",
    "Semail": "塞迈勒", "Somalia": "索马里", "Stikinia": "斯提金尼亚",
    "Sulu": "苏禄", "Turkey": "土耳其", "Woodlark": "伍德拉克",
    "Yangtze": "扬子", "Anuyi": "阿努伊", "Burma": "缅甸",
    "Mianlue": "勉略", "Panonian": "潘诺尼亚", "Basin": "盆地",
    "China": "中国", "Izu": "伊豆", "Pale": "古",
}

TERMS = {
    "accretionary Wedge": "增生楔", "back-arc basin": "弧后盆地",
    "backarc": "弧后", "back-arc": "弧后", "Forearc": "前弧",
    "rifting event": "裂谷事件", "rifting": "裂谷", "subducting": "俯冲",
    "subduction": "俯冲", "subductin": "俯冲", "accretion": "增生区",
    "island arc": "岛弧", "Oceanic Plate": "洋板块", "Ocean Plate": "洋板块",
    "oceanic plate": "洋板块", "ocean plate": "洋板块", "Microplate": "微板块",
    "Metacraton": "变质克拉通", "Platform": "台地", "Terrane": "地体",
    "Assembly": "组合体", "assembly": "组合体", "Shield": "地盾",
    "Block": "地块", "Blocks": "地块群", "Basin": "盆地", "Trough": "海槽",
    "Ocean": "洋", "ocean": "洋", "Sea": "海", "Plate": "板块", "plate": "板块",
    "Arc": "岛弧", "arc": "岛弧", "nucleus": "核心", "granulite unit": "麻粒岩单元",
    "Eastern": "东部", "Western": "西部", "Northern": "北部", "Southern": "南部",
    "Central": "中部", "North": "北部", "South": "南部", "East": "东部", "West": "西部",
    "Proto": "原始", "Stable": "稳定", "Trapped": "残留", "Missing": "缺失",
    "unnamed": "未命名", "Cretaceous": "白垩纪", "Carboniferous": "石炭纪",
    "under": "之下", "beneath": "之下", "from": "源自", "becomes": "演变为",
    "based on": "基于", "model": "模型", "half of": "半部", "flank of": "翼",
    "near": "附近", "and": "与", "of": "的", "north": "北部", "south": "南部",
    "basin": "盆地", "oceanic": "洋壳", "Subduction": "俯冲",
    "NE": "东北部", "NW": "西北部", "SE": "东南部", "SW": "西南部",
    "NORTH": "北部", "SOUTH": "南部", "BAB": "弧后盆地",
}

ACRONYMS = {
    "AACM": "北极阿拉斯加—楚科奇微板块", "AFRICA PLATE": "非洲板块",
    "ANS": "阿拉伯—努比亚地盾", "AUS": "澳大利亚板块", "EURASIA": "欧亚板块",
    "IBM": "伊豆—小笠原—马里亚纳板块", "ICB": "ICB板块", "IGU": "IGU构造组合体",
    "INDIA": "印度板块", "JUAN_DE_FUCA": "胡安·德富卡板块",
    "LATEA": "东南极洲板块", "LHR": "LHR板块", "NAM": "北美板块",
    "NAZ": "纳斯卡板块", "NFB": "北斐济盆地", "PAO": "古亚洲洋板块",
    "PSP": "菲律宾海板块", "RDLP": "RDLP板块", "SAM": "南美板块",
    "SCB": "华南地块", "SF": "圣弗朗西斯科地块", "SFB": "南斐济盆地",
    "SFBSW": "南斐济盆地西南部", "SFBWS": "南斐济盆地西部",
    "SFB_LD": "南斐济盆地—劳盆地", "TRM": "塔里木板块", "WAC": "西非克拉通",
    "KUL": "库拉板块",
}

# 同一个英文名在 Coastline 与动态拓扑中可能指向不同语义。例如 Eurasia 作为
# Coastline 名称译作“欧亚大陆”，作为一级闭合板块拓扑则应显示为“欧亚板块”。
TOPOLOGY_DISPLAY_OVERRIDES = {
    "Africa": "非洲板块",
    "Antarctica": "南极洲板块",
    "Arabia": "阿拉伯板块",
    "Australia": "澳大利亚板块",
    "Caribbean": "加勒比板块",
    "Cocos": "科科斯板块",
    "Eurasia": "欧亚板块",
    "Farallon": "法拉隆板块",
    "Greenland": "格陵兰板块",
    "India": "印度板块",
    "Izanagi": "伊邪那岐板块",
    "Kula": "库拉板块",
    "Mariana": "马里亚纳板块",
    "North America": "北美板块",
    "Pacific": "太平洋板块",
    "South America": "南美板块",
    "Tonga": "汤加板块",
}


def topology_names() -> set[str]:
    names: set[str] = set()
    for relative_path in TOPOLOGY_PATHS:
        for feature in pygplates.FeatureCollection(str(MODEL_DIR / relative_path)):
            if (feature.get_feature_type() ==
                    pygplates.FeatureType.gpml_topological_closed_plate_boundary and
                    feature.get_name()):
                names.add(feature.get_name())
    return names


def technical_base(source: str) -> str:
    value = source.strip()
    if value.startswith("JUAN_DE_FUCA"):
        return "JUAN_DE_FUCA"
    value = re.sub(r"\s+(?:GS|AT)$", "", value)
    for prefix in ("Africa", "Antarctica", "Arabia", "Australia", "Caribbean", "Cocos",
                   "Eurasia", "Farallon", "Greenland", "Izanagi", "Izu", "Kula",
                   "Mariana", "Pacific", "Tonga"):
        if re.match(rf"^{prefix}(?:\s+[A-Z]{{2,}}[_ ]|_[0-9])", value):
            return prefix
    value = re.sub(r"\s+[A-Z]{2,}(?:_[A-Z0-9.]+)+$", "", value)
    value = re.sub(r"_[A-Z]{2,}(?:_[0-9A-Za-z.]+)+$", "", value)
    value = re.sub(r"_[0-9.]+(?:_[0-9A-Za-z.]+)+$", "", value)
    value = re.sub(r"\s+\d+(?:[-_]\d+(?:\.\d+)?)?(?:\s+(?:GS|AT))?$", "", value)
    value = re.sub(r"\s+(?:NW|NE|SW|SE)\d+$", "", value)
    value = re.sub(r"\s+from\s+PB\d+(?:\s+GS)?$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:FAR|PAC|SOL)$", "", value)
    return value.strip()


def replace_phrase(value: str, source: str, target: str) -> str:
    pattern = rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])"
    return re.sub(pattern, lambda _: target, value)


def translate_topology(source: str, known: dict[str, str]) -> tuple[str, str]:
    base = technical_base(source)
    if base in TOPOLOGY_DISPLAY_OVERRIDES:
        return TOPOLOGY_DISPLAY_OVERRIDES[base], "惯用译名"
    if base in ACRONYMS:
        return ACRONYMS[base], "惯用译名"
    if base in known:
        display = known[base]
        if not any(term in display for term in ("板块", "大陆", "陆块", "地体", "洋", "海", "盆地")):
            display += "板块"
        return display, "惯用译名"

    display = base
    combined = {**known, **GLOSSARY, **ACRONYMS, **TERMS}
    for phrase, translated in sorted(combined.items(), key=lambda item: len(item[0]), reverse=True):
        display = replace_phrase(display, phrase, translated)
    display = display.replace("  ", " ").strip()
    display = display.replace("大陆 板块", "大陆")
    display = display.replace("洋 洋板块", "洋板块").replace("洋 洋", "洋")
    display = display.replace("洋 板块", "洋板块").replace("海 板块", "海板块")
    display = display.replace("地块 板块", "地块").replace("盆地 板块", "盆地板块")
    display = display.replace("板块板块", "板块").replace("组合体组合体", "组合体")
    display = re.sub(r"\s*[-–]\s*", "—", display)
    display = display.replace("—板块", "板块")
    display = re.sub(r"(?<=[\u4e00-\u9fff）])\s+", "", display)
    display = re.sub(r"\s+(?=[\u4e00-\u9fff（])", "", display)
    display = display.replace("板块板块", "板块").replace("组合体组合体", "组合体")
    display = display.replace(" (", "（").replace(")", "）")
    display = display.replace("?", "？")
    if not any("\u4e00" <= character <= "\u9fff" for character in display):
        display = f"{display}构造板块"
    if not any(term in display for term in
               ("板块", "大陆", "陆块", "地块", "地体", "克拉通", "洋", "海", "盆地",
                "台地", "组合体", "岛弧", "地盾", "增生区", "核心")):
        display += "板块"
    basis = "组合翻译" if not re.search(r"[A-Za-z][a-z]", display) else "审慎音译"
    return display, basis


def main() -> None:
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    entries = {entry["source"]: entry for entry in document["regions"]}
    known = {
        source: entry["display"] for source, entry in entries.items()
        if MODEL_REFERENCE not in entry.get("reference", "")
    }
    added = 0
    for source in sorted(topology_names()):
        display, basis = translate_topology(source, known)
        topology_reference = (
            f"{MODEL_REFERENCE}；MULLER2022 拓扑源名逐项核对；"
            f"中文地名与构造地质术语参照{TERM_REFERENCE}，模型版本后缀不进入显示名。"
        )
        if source in entries and MODEL_REFERENCE not in entries[source].get("reference", ""):
            entries[source]["topologyDisplay"] = display
            entries[source]["topologyBasis"] = basis
            entries[source]["topologyReference"] = topology_reference
            continue
        entries[source] = {
            "source": source,
            "display": display,
            "topologyDisplay": display,
            "basis": basis,
            "reference": topology_reference,
        }
        added += 1

    output = {
        "languageCode": "zh-CN",
        "reviewPolicy": "保留全部英文 source；优先通行译名，其次术语组合或审慎音译；不显示模型年代后缀。",
        "sources": [MODEL_REFERENCE, TERM_REFERENCE],
        "regions": [entries[source] for source in sorted(entries)],
    }
    lines = ["{", '  "languageCode": "zh-CN",',
             f'  "reviewPolicy": {json.dumps(output["reviewPolicy"], ensure_ascii=False)},',
             f'  "sources": {json.dumps(output["sources"], ensure_ascii=False)},',
             '  "regions": [']
    serialized = ["    " + json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                  for entry in output["regions"]]
    lines.append(",\n".join(serialized))
    lines.extend(("  ]", "}"))
    CATALOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"区域中文目录共 {len(entries)} 项；新增拓扑名称 {added} 项")


if __name__ == "__main__":
    main()
