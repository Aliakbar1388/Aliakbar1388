# -*- coding: utf-8 -*-
"""Build a beautiful RTL Persian study-notes PDF from markdown files.

Markdown subset:
  # H1 lesson banner | ## H2 | ### H3 | plain paragraphs | - bullets | 1. numbers
  :::tip|warn|exam|info title ... :::   boxes
  > quote lines                          quote block
  | a | b |   (+ |---| separator)        RTL table
  **bold**                               inline bold
  <!--pagebreak-->                       forced break
Usage: python build_pdf.py <md_dir> <out.pdf>     (two-pass for TOC page numbers)
"""
import os, re, sys, glob
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
    Table, TableStyle, Spacer, PageBreak, HRFlowable, NextPageTemplate)
import arabic_reshaper
from bidi.algorithm import get_display

# ---------------- fonts ----------------
FDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts')
pdfmetrics.registerFont(TTFont('V',  f'{FDIR}/Vazirmatn-Regular.ttf'))
pdfmetrics.registerFont(TTFont('VM', f'{FDIR}/Vazirmatn-Medium.ttf'))
pdfmetrics.registerFont(TTFont('VB', f'{FDIR}/Vazirmatn-Bold.ttf'))
pdfmetrics.registerFont(TTFont('VX', f'{FDIR}/Vazirmatn-ExtraBold.ttf'))
pdfmetrics.registerFont(TTFont('VS', f'{FDIR}/Vazirmatn-SemiBold.ttf'))
# Amiri (نسخ عربی خوش‌نویس) برای آیات و احادیث داخل نقل‌قول‌ها
pdfmetrics.registerFont(TTFont('AR',  f'{FDIR}/Amiri-Regular.ttf'))
pdfmetrics.registerFont(TTFont('ARB', f'{FDIR}/Amiri-Bold.ttf'))

_HAS_HARAKAT = TTFont('chk', f'{FDIR}/Vazirmatn-Regular.ttf').face.charToGlyph.get(0x064E, 0) != 0
RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    'delete_harakat': not _HAS_HARAKAT,
    'support_ligatures': True,
})
BOLD_MAP = {'V': 'VB', 'VM': 'VB', 'VB': 'VB', 'VX': 'VX', 'VS': 'VB', 'AR': 'ARB'}

# ---------------- colors ----------------
NAVY   = colors.HexColor('#173A5E')
NAVY2  = colors.HexColor('#22507F')
GOLD   = colors.HexColor('#C79A3B')
GOLDL  = colors.HexColor('#EAD9B0')
TEAL   = colors.HexColor('#1F7A6C')
INK    = colors.HexColor('#26313D')
GRAY   = colors.HexColor('#6B7684')
LINE   = colors.HexColor('#D8DFE7')
TIPBG, TIPBD = colors.HexColor('#E9F2FB'), colors.HexColor('#8FB8E0')
WARNBG, WARNBD = colors.HexColor('#FDF3E2'), colors.HexColor('#E3B768')
EXAMBG, EXAMBD = colors.HexColor('#E9F6EE'), colors.HexColor('#83C6A0')
NOTEBG, NOTEBD = colors.HexColor('#F3F1FA'), colors.HexColor('#AFA6DD')
QBG = colors.HexColor('#F7F9FC')

FA = '۰۱۲۳۴۵۶۷۸۹'
def fa(n):
    return ''.join(FA[int(c)] if c.isdigit() else c for c in str(n))

def vis(s):
    return get_display(RESHAPER.reshape(s), base_dir='R')

B0, B1 = '\ue000', '\ue001'

def vis_line(s, sb=False):
    """reshape+reorder one line. sb = inside a **bold** span at line start.
    Markers are stored REVERSED (B1 at logical start, B0 at logical end) so that
    after bidi reordering they end up as <b>...</b> in visual order."""
    if '**' not in s and not sb:
        return vis(s)
    parts = s.split('**')
    out = []
    for j, p in enumerate(parts):
        in_b = sb if (j % 2 == 0) else (not sb)
        out.append(B1 + p + B0 if in_b else p)
    return vis(''.join(out)).replace(B0, '<b>').replace(B1, '</b>')

def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def _seg_width(seg, fname, fsize):
    if not seg:
        return 0.0
    return pdfmetrics.stringWidth(RESHAPER.reshape(seg), fname, fsize)

def wrap_lines(text, fname, fsize, maxw):
    """wrap logical text on spaces (bold-aware).
    Returns [(line_text, start_inside_bold), ...]."""
    sp = pdfmetrics.stringWidth(' ', fname, fsize)
    words = text.split(' ')
    lines, cur = [], []
    cur_w = 0.0
    cur_sb = False
    bold = False
    start_i = 0
    for wi, w in enumerate(words):
        sb_here = bold
        segs = w.split('**')
        w_w = 0.0
        for j, seg in enumerate(segs):
            in_b = bold if (j % 2 == 0) else (not bold)
            f = BOLD_MAP.get(fname, 'VB') if in_b else fname
            w_w += _seg_width(seg, f, fsize)
        n_stars = len(segs) - 1
        trial = cur_w + (sp if cur else 0) + w_w
        if cur and trial > maxw:
            lines.append((' '.join(words[start_i:wi]), cur_sb))
            start_i = wi
            cur = [w]
            cur_w = w_w
            cur_sb = sb_here
        else:
            cur.append(w)
            cur_w = trial
        if n_stars % 2 == 1:
            bold = not bold
    if cur:
        lines.append((' '.join(words[start_i:]), cur_sb))
    return lines

# ---------------- styles ----------------
def mk_styles():
    st = {}
    st['body'] = ParagraphStyle('body', fontName='V', fontSize=10.5, leading=18.5,
        textColor=INK, alignment=TA_RIGHT, spaceAfter=6)
    st['bullet'] = ParagraphStyle('bullet', parent=st['body'], spaceAfter=3.5)
    st['H1'] = ParagraphStyle('H1P', fontName='VX', fontSize=17.5, leading=24,
        textColor=colors.white, alignment=TA_RIGHT)
    st['H2'] = ParagraphStyle('H2P', fontName='VB', fontSize=13.5, leading=20,
        textColor=NAVY, alignment=TA_RIGHT)
    st['H3'] = ParagraphStyle('H3P', fontName='VS', fontSize=11.5, leading=18,
        textColor=TEAL, alignment=TA_RIGHT)
    st['boxtitle'] = ParagraphStyle('BT', fontName='VX', fontSize=10.5, leading=17,
        textColor=colors.white, alignment=TA_RIGHT)
    st['boxbody'] = ParagraphStyle('BB', fontName='V', fontSize=10, leading=17,
        textColor=INK, alignment=TA_RIGHT)
    st['quote'] = ParagraphStyle('QP', fontName='VM', fontSize=10.5, leading=19,
        textColor=colors.HexColor('#4A4230'), alignment=TA_RIGHT)
    st['quoteAR'] = ParagraphStyle('QPA', fontName='AR', fontSize=12.5, leading=22,
        textColor=colors.HexColor('#4A4230'), alignment=TA_RIGHT)
    st['th'] = ParagraphStyle('TH', fontName='VB', fontSize=10, leading=16,
        textColor=colors.white, alignment=TA_CENTER)
    st['td'] = ParagraphStyle('TD', fontName='V', fontSize=9.8, leading=16,
        textColor=INK, alignment=TA_RIGHT)
    st['tocT'] = ParagraphStyle('TOCT', fontName='VX', fontSize=17, leading=24,
        textColor=NAVY, alignment=TA_RIGHT)
    st['tocRow'] = ParagraphStyle('TOCR', fontName='VM', fontSize=11, leading=22,
        textColor=INK, alignment=TA_RIGHT)
    st['tocPg'] = ParagraphStyle('TOCP', fontName='VS', fontSize=10.5, leading=22,
        textColor=NAVY, alignment=TA_CENTER)
    st['tocDot'] = ParagraphStyle('TOCD', fontName='V', fontSize=8, leading=22,
        textColor=GOLD, alignment=TA_CENTER)
    return st
S = mk_styles()

MAXW = A4[0] - 36*mm

def P(text, style, maxw=None):
    if maxw is None:
        maxw = MAXW - 4
    lines = wrap_lines(text, style.fontName, style.fontSize, maxw - 1)
    body = '<br/>'.join(vis_line(esc(l), sb) for l, sb in lines)
    return Paragraph(body, style)

# ---------------- boxes / tables ----------------
BOXES = {
    'tip':  ('نکته', TIPBG, TIPBD),
    'warn': ('هشدار', WARNBG, WARNBD),
    'exam': ('اکسیر امتحان', EXAMBG, EXAMBD),
    'info': ('آگاه باش', NOTEBG, NOTEBD),
}

def h1_flowable(title):
    cell = P(title, S['H1'], MAXW - 30)
    t = Table([[cell]], colWidths=[MAXW])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NAVY),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LINEAFTER', (0, 0), (0, -1), 5, GOLD),
    ]))
    t._meta = (0, title)
    bar = Table([['']], colWidths=[MAXW], rowHeights=[2.6])
    bar.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), GOLD)]))
    return [t, bar, Spacer(1, 9)]

def box_flowable(kind, title, body_lines):
    label, bg, bd = BOXES.get(kind, BOXES['info'])
    dark = {'tip': colors.HexColor('#1C5D99'), 'warn': colors.HexColor('#8A5A00'),
            'exam': colors.HexColor('#1E7A4B'), 'info': colors.HexColor('#5B4CA8')}.get(kind, NAVY)
    tstyle = ParagraphStyle(f'btx_{kind}', parent=S['boxtitle'], textColor=dark)
    inner = [P(label + (': ' + title if title else ''), tstyle, MAXW - 30)]
    for ln in body_lines:
        if ln.strip():
            inner.append(P(ln, S['boxbody'], MAXW - 30))
    t = Table([[inner]], colWidths=[MAXW])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('BOX', (0, 0), (-1, -1), 0.9, bd),
        ('LINEAFTER', (0, 0), (0, -1), 4, bd),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return [Spacer(1, 4), t, Spacer(1, 8)]

def quote_flowable(lines):
    # خط عربی (آیه/حدیث — بدون حروف فارسی پ چ ژ گ ک) با فونت امیریِ نسخی
    def pick(ln):
        stl = S['quoteAR'] if not any(ch in ln for ch in 'پچژگک') else S['quote']
        return P(ln, stl, MAXW - 34)
    inner = [pick(ln) for ln in lines if ln.strip()]
    t = Table([[inner]], colWidths=[MAXW])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), QBG),
        ('LINEAFTER', (0, 0), (0, -1), 3, GOLD),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return [Spacer(1, 3), t, Spacer(1, 7)]

def table_flowable(rows):
    if not rows:
        return []
    ncol = max(len(r) for r in rows)
    rows = [r + [''] * (ncol - len(r)) for r in rows]
    colw = MAXW / ncol
    data = []
    for ri, row in enumerate(rows):
        stl = S['th'] if ri == 0 else S['td']
        data.append([P(c, stl, colw - 12) for c in row])
    data = [list(reversed(r)) for r in data]     # RTL columns
    t = Table(data, colWidths=[colw] * ncol, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY2),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE),
        ('BOX', (0, 0), (-1, -1), 0.9, NAVY2),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F4F8FC')]),
    ]))
    return [Spacer(1, 4), t, Spacer(1, 9)]

# ---------------- md parser ----------------
def parse_file(path):
    lines = open(path, encoding='utf-8').read().split('\n')
    specs, i = [], 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1; continue
        if s == '<!--pagebreak-->':
            specs.append({'t': 'break'}); i += 1; continue
        if s.startswith('# '):
            specs.append({'t': 'h1', 'text': s[2:].strip()}); i += 1; continue
        if s.startswith('## '):
            specs.append({'t': 'h2', 'text': s[3:].strip()}); i += 1; continue
        if s.startswith('### '):
            specs.append({'t': 'h3', 'text': s[4:].strip()}); i += 1; continue
        m = re.match(r'^:::(tip|warn|exam|info)\s*(.*)$', s)
        if m:
            kind, title = m.group(1), m.group(2).strip()
            body, i = [], i + 1
            while i < len(lines) and lines[i].strip() != ':::':
                body.append(lines[i].rstrip()); i += 1
            i += 1
            specs.append({'t': 'box', 'kind': kind, 'title': title, 'body': body}); continue
        if s.startswith('>'):
            q = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                q.append(lines[i].strip().lstrip('>').strip()); i += 1
            specs.append({'t': 'quote', 'lines': q}); continue
        if s.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
                    rows.append(cells)
                i += 1
            specs.append({'t': 'table', 'rows': rows}); continue
        if s.startswith('- '):
            while i < len(lines) and lines[i].strip().startswith('- '):
                specs.append({'t': 'bullet', 'text': lines[i].strip()[2:].strip()}); i += 1
            continue
        m = re.match(r'^(\d+)[\.\)]\s+(.*)$', s)
        if m:
            while i < len(lines):
                mm = re.match(r'^(\d+)[\.\)]\s+(.*)$', lines[i].strip())
                if not mm: break
                specs.append({'t': 'num', 'n': int(mm.group(1)), 'text': mm.group(2).strip()}); i += 1
            continue
        buf = [s]; i += 1
        while i < len(lines):
            nx = lines[i].strip()
            if (not nx or nx.startswith(('#', '|', '- ', '>', ':::', '<!--')) or
                    re.match(r'^\d+[\.\)]\s+', nx)):
                break
            buf.append(nx); i += 1
        specs.append({'t': 'para', 'text': ' '.join(buf)}); continue
    return specs

def _build_list(files, first_ok):
    out, first_h1 = [], first_ok
    for path in files:
        for sp in parse_file(path):
            t = sp['t']
            if t == 'break':
                out.append(PageBreak())
            elif t == 'h1':
                if not first_h1:
                    out.append(PageBreak())
                first_h1 = False
                out.extend(h1_flowable(sp['text']))
            elif t == 'h2':
                p = P(sp['text'], S['H2']); p._meta = (1, sp['text'])
                out.append(Spacer(1, 8)); out.append(p)
                out.append(HRFlowable(width='100%', thickness=1, color=GOLDL,
                                      spaceBefore=1, spaceAfter=6, lineCap='round'))
            elif t == 'h3':
                out.append(P(sp['text'], S['H3']))
            elif t == 'para':
                out.append(P(sp['text'], S['body']))
            elif t == 'bullet':
                out.append(P('•  ' + sp['text'], S['bullet']))
            elif t == 'num':
                out.append(P(fa(sp['n']) + '.  ' + sp['text'], S['bullet']))
            elif t == 'box':
                out.extend(box_flowable(sp['kind'], sp['title'], sp['body']))
            elif t == 'quote':
                out.extend(quote_flowable(sp['lines']))
            elif t == 'table':
                out.extend(table_flowable(sp['rows']))
    return out

# ---------------- cover & chrome ----------------
def draw_cover(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 118*mm, w, 118*mm, stroke=0, fill=1)
    canvas.setStrokeColor(GOLD); canvas.setLineWidth(1.6)
    canvas.rect(14*mm, h - 112*mm, w - 28*mm, 106*mm, stroke=1, fill=0)
    canvas.setFillColor(GOLDL); canvas.setFont('VM', 12)
    canvas.drawCentredString(w/2, h - 24*mm, vis('بسم‌الله‌الرحمن‌الرحیم'))
    canvas.setFont('VX', 40); canvas.setFillColor(colors.white)
    canvas.drawCentredString(w/2, h - 46*mm, vis('جزوهٔ جامع درسی'))
    canvas.setFont('VX', 52); canvas.setFillColor(GOLDL)
    canvas.drawCentredString(w/2, h - 72*mm, vis('دین و زندگی (۳)'))
    canvas.setFont('VS', 16); canvas.setFillColor(colors.white)
    canvas.drawCentredString(w/2, h - 88*mm, vis('قرآن و تعلیمات دینی  —  پایهٔ دوازدهم'))
    canvas.setFillColor(GOLD)
    canvas.rect(30*mm, h - 136*mm, w - 60*mm, 13*mm, stroke=0, fill=1)
    canvas.setFillColor(NAVY); canvas.setFont('VB', 14)
    canvas.drawCentredString(w/2, h - 131.7*mm, vis('رشتهٔ ادبیات و علوم انسانی'))
    canvas.setStrokeColor(GOLD); canvas.setLineWidth(1)
    canvas.line(35*mm, h - 150*mm, w - 35*mm, h - 150*mm)
    canvas.setFillColor(TEAL)
    canvas.circle(w/2, h - 166*mm, 7*mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white); canvas.setFont('VX', 16)
    canvas.drawCentredString(w/2, h - 171.5*mm, vis('۳'))
    canvas.setFillColor(colors.HexColor('#F4F7FA')); canvas.setStrokeColor(LINE)
    canvas.roundRect(22*mm, h - 236*mm, w - 44*mm, 52*mm, 4*mm, stroke=1, fill=1)
    canvas.setFillColor(INK); canvas.setFont('VM', 12.5)
    info = ['کد کتاب: ۱۱۲۲۰۵   |   چاپ هشتم، سال ۱۴۰۴',
            'پدیدآورنده: سازمان پژوهش و برنامه‌ریزی آموزشی',
            'ویژهٔ دانش‌آموزان رشتهٔ علوم انسانی — ۱۳ درس، ۲ بخش']
    y = h - 196*mm
    for t in info:
        canvas.drawCentredString(w/2, y, vis(t)); y -= 8*mm
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, w, 16*mm, stroke=0, fill=1)
    canvas.setFillColor(GOLDL); canvas.setFont('VM', 10.5)
    canvas.drawCentredString(w/2, 5.6*mm, vis('تهیه‌شده از متن کتاب درسی — مناسب برای مطالعه، مرور و آمادگی امتحان'))
    canvas.restoreState()

def draw_main(canvas, doc):
    w, h = A4
    canvas.saveState()
    if canvas.getPageNumber() >= 2:
        canvas.setFont('VM', 8); canvas.setFillColor(GRAY)
        canvas.drawRightString(w - 18*mm, h - 12.5*mm,
            vis('جزوهٔ جامع دین و زندگی (۳) — پایهٔ دوازدهم، رشتهٔ علوم انسانی'))
        canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.7)
        canvas.line(18*mm, h - 14.6*mm, w - 18*mm, h - 14.6*mm)
        canvas.setStrokeColor(LINE); canvas.setLineWidth(0.5)
        canvas.line(18*mm, 13.2*mm, w - 18*mm, 13.2*mm)
        canvas.setFont('V', 8.5); canvas.setFillColor(GRAY)
        canvas.drawCentredString(w/2, 8.6*mm, vis('صفحهٔ ' + fa(canvas.getPageNumber())))
        canvas.drawRightString(w - 18*mm, 8.6*mm, vis('کد کتاب: ۱۱۲۲۰۵'))
        canvas.drawString(18*mm, 8.6*mm, vis('علوم انسانی'))
    canvas.restoreState()

def make_toc_flowables(entries):
    flow = [Spacer(1, 8), P('فهرست مطالب', S['tocT'])]
    flow.append(HRFlowable(width='100%', thickness=2, color=GOLD,
                           spaceBefore=6, spaceAfter=10))
    rows = []
    for title, page in entries:
        rows.append([
            P(fa(page), S['tocPg']),
            P('٭  ٭  ٭  ٭', S['tocDot']),
            P(title, S['tocRow'], MAXW - 34*mm),
        ])
    if not rows:
        rows = [[P('', S['tocPg']), P('', S['tocDot']), P('—', S['tocRow'])]]
    colt = MAXW - 30*mm
    tb = Table(rows, colWidths=[14*mm, 16*mm, colt])
    tb.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, LINE),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    flow += [tb, PageBreak()]
    return flow

# ---------------- doc template ----------------
class Doc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        BaseDocTemplate.__init__(self, filename, **kw)
        cover_frame = Frame(0, 0, A4[0], A4[1], 0, 0, 0, 0, id='cover')
        main_frame = Frame(18*mm, 16*mm, A4[0]-36*mm, A4[1]-38*mm,
                           leftPadding=0, rightPadding=0, topPadding=0,
                           bottomPadding=0, id='main')
        self.addPageTemplates([
            PageTemplate(id='cover', frames=[cover_frame], onPage=draw_cover),
            PageTemplate(id='main', frames=[main_frame], onPage=draw_main),
        ])
        self.h1_entries = []
    def afterFlowable(self, flowable):
        meta = getattr(flowable, '_meta', None)
        if not meta:
            return
        level, title = meta
        key = f'bm{self.page}_{level}_{abs(hash(title)) % 10**7}'
        try:
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=level, closed=(level > 0))
        except Exception:
            pass
        if level == 0:
            self.h1_entries.append((title, self.page))

def build_pdf(md_dir, out_pdf):
    files = sorted(glob.glob(os.path.join(md_dir, '*.md')))
    front = [f for f in files if os.path.basename(f).startswith('00-')]
    rest = [f for f in files if not os.path.basename(f).startswith('00-')]
    if not files:
        raise SystemExit(f'no md files in {md_dir}')

    def make_story(entries):
        story = [NextPageTemplate('main'), Spacer(1, 1), PageBreak()]
        story += _build_list(front, first_ok=True)
        story += make_toc_flowables(entries)
        story += _build_list(rest, first_ok=True)
        return story

    # iterate until TOC page numbers stabilize: pass 1 uses an empty/partial
    # TOC (may occupy a different number of pages than the full TOC), so we
    # rebuild with the previous pass's entries until the layout stops moving.
    prev = []
    ents = None
    for _ in range(6):
        doc = Doc(out_pdf)
        doc.build(make_story(prev))
        ents = doc.h1_entries
        if ents == prev:
            break
        prev = ents
    return out_pdf, ents

if __name__ == '__main__':
    md_dir = sys.argv[1] if len(sys.argv) > 1 else '/home/user/Aliakbar1388/joze/md'
    out = sys.argv[2] if len(sys.argv) > 2 else '/home/user/Aliakbar1388/joze/joze.pdf'
    pdf, ents = build_pdf(md_dir, out)
    print('OK ->', pdf)
    try:
        from pypdf import PdfReader
        print('pages:', len(PdfReader(pdf).pages))
    except Exception as e:
        print('pages: ?', e)
    for t, p in ents:
        print(f'  p{p:>3}  {t}')
