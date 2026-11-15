import 'server-only';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import fontkit from '@pdf-lib/fontkit';
import { PDFDocument, rgb, type PDFFont, type PDFPage } from 'pdf-lib';

const PAGE_WIDTH = 595.28; // A4
const PAGE_HEIGHT = 841.89;
const MARGIN = 56;
const MAX_WIDTH = PAGE_WIDTH - MARGIN * 2;

const TEXT_COLOR = rgb(0.12, 0.12, 0.14);
const MUTED_COLOR = rgb(0.45, 0.45, 0.5);

let cachedFonts: Promise<{ regular: Uint8Array; bold: Uint8Array }> | null = null;

/**
 * Loads Unicode TrueType fonts (full Turkish character support: ç, ğ, ı, İ, ö, ş, ü).
 * First checks bundled fonts in `lib/fonts/`, then falls back to Windows system Arial.
 */
function loadFontBytes(): Promise<{ regular: Uint8Array; bold: Uint8Array }> {
  if (!cachedFonts) {
    cachedFonts = (async () => {
      const candidates = [
        {
          regular: path.join(process.cwd(), 'lib', 'fonts', 'regular.ttf'),
          bold: path.join(process.cwd(), 'lib', 'fonts', 'bold.ttf'),
        },
        {
          regular: 'C:\\Windows\\Fonts\\arial.ttf',
          bold: 'C:\\Windows\\Fonts\\arialbd.ttf',
        },
      ];
      for (const pair of candidates) {
        try {
          const [regular, bold] = await Promise.all([readFile(pair.regular), readFile(pair.bold)]);
          return { regular, bold };
        } catch {
          // try next candidate
        }
      }
      throw new Error('Unicode font files (regular.ttf / bold.ttf) could not be found.');
    })();
  }
  return cachedFonts;
}

function makeSanitizer(font: PDFFont): (text: string) => string {
  const codePointSet = new Set<number>(font.getCharacterSet());
  return (text: string) => {
    let out = '';
    for (const ch of text.replace(/\r/g, '').replace(/\t/g, '    ')) {
      if (ch === '\n') {
        out += ch;
        continue;
      }
      const cp = ch.codePointAt(0);
      out += cp !== undefined && codePointSet.has(cp) ? ch : '?';
    }
    return out;
  };
}

function wrapText(text: string, font: PDFFont, size: number, maxWidth: number): string[] {
  const lines: string[] = [];
  let current = '';
  for (const word of text.split(/ +/)) {
    const candidate = current ? `${current} ${word}` : word;
    if (font.widthOfTextAtSize(candidate, size) <= maxWidth) {
      current = candidate;
      continue;
    }
    if (current) lines.push(current);
    // Hard-break words that are longer than a full line (e.g. URLs).
    let remainder = word;
    while (font.widthOfTextAtSize(remainder, size) > maxWidth) {
      let cut = remainder.length - 1;
      while (cut > 1 && font.widthOfTextAtSize(remainder.slice(0, cut), size) > maxWidth) cut -= 1;
      lines.push(remainder.slice(0, cut));
      remainder = remainder.slice(cut);
    }
    current = remainder;
  }
  if (current) lines.push(current);
  return lines;
}

export interface PdfInput {
  title?: string;
  content: string;
}

/** Renders UTF-8 / Turkish text (with light markdown: #, ##, - bullets, **bold**) to a PDF. */
export async function createPdfFromText({ title, content }: PdfInput): Promise<Uint8Array> {
  const pdf = await PDFDocument.create();
  pdf.registerFontkit(fontkit);
  pdf.setTitle(title ?? 'Doküman');
  pdf.setCreator('Mini Agent');
  pdf.setProducer('Mini Agent (pdf-lib + fontkit)');
  pdf.setCreationDate(new Date());

  const fontBytes = await loadFontBytes();
  const regular = await pdf.embedFont(fontBytes.regular, { subset: true });
  const bold = await pdf.embedFont(fontBytes.bold, { subset: true });
  const sanitizeRegular = makeSanitizer(regular);
  const sanitizeBold = makeSanitizer(bold);

  let page: PDFPage = pdf.addPage([PAGE_WIDTH, PAGE_HEIGHT]);
  let y = PAGE_HEIGHT - MARGIN;

  const drawLines = (text: string, font: PDFFont, size: number, indent = 0): void => {
    const lineHeight = size * 1.4;
    for (const line of wrapText(text, font, size, MAX_WIDTH - indent)) {
      if (y - lineHeight < MARGIN) {
        page = pdf.addPage([PAGE_WIDTH, PAGE_HEIGHT]);
        y = PAGE_HEIGHT - MARGIN;
      }
      page.drawText(line, { x: MARGIN + indent, y: y - size, size, font, color: TEXT_COLOR });
      y -= lineHeight;
    }
  };

  if (title?.trim()) {
    drawLines(sanitizeBold(title.trim()), bold, 20);
    y -= 10;
  }

  for (const rawLine of content.split('\n')) {
    const line = rawLine.replace(/\*\*(.+?)\*\*/g, '$1').trimEnd();
    if (!line.trim()) {
      y -= 8;
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1]?.length ?? 1;
      y -= 6;
      drawLines(sanitizeBold(heading[2] ?? ''), bold, level === 1 ? 16 : level === 2 ? 14 : 12);
      continue;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      drawLines(`\u2022 ${sanitizeRegular(bullet[1] ?? '')}`, regular, 11, 12);
      continue;
    }
    drawLines(sanitizeRegular(line), regular, 11);
  }

  const pages = pdf.getPages();
  pages.forEach((p, index) => {
    p.drawText(sanitizeRegular(`Sayfa ${index + 1} / ${pages.length}`), {
      x: MARGIN,
      y: MARGIN / 2,
      size: 9,
      font: regular,
      color: MUTED_COLOR,
    });
  });

  return pdf.save();
}
