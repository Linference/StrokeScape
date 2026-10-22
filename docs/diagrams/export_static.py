"""Build self-contained, non-animated README SVGs from the diagram HTML."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
NS = '{http://www.w3.org/2000/svg}'
ET.register_namespace('', NS[1:-1])


def build(name):
    path = ROOT / (name + '.html')
    document = path.read_text(encoding='utf-8')
    if name == 'workflow':
        # The upstream workflow template's generic agent legend is replaced
        # with this project's actual component semantics.
        legend = '<!-- Legend -->\n<text x="175" y="428" class="t-primary" font-size="10" font-weight="600">图例</text>'
        for x, style, label in [(175, 'frontend', '交互与渲染'), (300, 'backend', '图像与算法'),
                                 (425, 'database', '作品与文件'), (550, 'external', '输入与交付')]:
            rect = f'x="{x}" y="440" width="14" height="9" rx="2"'
            legend += f'<rect {rect} class="c-mask"/><rect {rect} class="c-{style}" stroke-width="1"/>'
            legend += f'<text x="{x + 20}" y="448" class="t-muted" font-size="8">{label}</text>'
        document = re.sub(r'<!-- Legend -->[\s\S]*?</svg>', legend + '</svg>', document, count=1)
    document = '\n'.join(line.rstrip() for line in document.splitlines()) + '\n'
    path.write_text(document, encoding='utf-8')
    css = re.search(r'<style[^>]*>([\s\S]*?)</style>', document).group(1)
    light = re.search(r'\[data-theme="light"\]\s*\{([^}]+)\}', css).group(1)
    css = re.sub(r'\bsvg\s*\{\s*width:\s*100%;[\s\S]*?\}', 'svg { display:block; }', css, count=1)
    svg = ET.fromstring(re.search(r'<svg\b[\s\S]*?</svg>', document).group(0))
    _, _, width, height = svg.attrib['viewBox'].split()
    svg.set('width', width)
    svg.set('height', height)
    svg.attrib.pop('style', None)
    for parent in list(svg.iter()):
        for child in list(parent):
            if child.tag == NS + 'circle' and any(item.tag == NS + 'animateMotion' for item in child):
                parent.remove(child)
    style = ET.Element(NS + 'style')
    style.text = css + '\n@media (prefers-color-scheme: light) {:root,svg {' + light + '}}\n' + """
svg {font-family:'Microsoft YaHei','PingFang SC',system-ui,sans-serif}
.a-emphasis,.a-default,.a-dashed,.a-security {animation:none!important;filter:none!important;opacity:1!important}
.a-emphasis,.a-default {stroke-dasharray:none!important}
.export-bg {fill:var(--bg)}
"""
    svg.insert(0, style)
    svg.insert(1, ET.Element(NS + 'rect', {'class': 'export-bg', 'width': '100%', 'height': '100%'}))
    title = ET.Element(NS + 'text', {'x': '40', 'y': '28', 'class': 't-primary', 'font-size': '16', 'font-weight': '600'})
    title.text = '从静态图像到可播放的数字笔触' if name == 'workflow' else '核心技术架构 · 本机运行与共享渲染'
    svg.insert(2, title)
    target = path.with_suffix('.svg')
    ET.ElementTree(svg).write(target, encoding='utf-8', xml_declaration=True)
    target.write_text('\n'.join(line.rstrip() for line in target.read_text(encoding='utf-8').splitlines()) + '\n', encoding='utf-8')


if __name__ == '__main__':
    for name in ('workflow', 'architecture'):
        build(name)
        print(ROOT / (name + '.svg'))
