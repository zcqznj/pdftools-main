# -*- coding:utf-8*-
import os
import time
import sys
import warnings
import hashlib
from PySide6.QtWidgets import QApplication, QDialog
from ui_mainwinmergepdf import Ui_MainWindow
import fitz
import re


if not sys.warnoptions:
    warnings.simplefilter("ignore")


class MainDialog(QDialog):
    def __init__(self, parent=None):
        super(MainDialog, self).__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

    # 自然排序：
    # - 英文字母：忽略大小写主序，同字母小写优先 → a < A < b < B
    # - 内嵌数字：按数值大小 → 1 < 2 < 9 < 10（如 a2.pdf < a10.pdf）
    def natural_key(self, filepath):
        filename = os.path.basename(filepath)

        def convert(part):
            if part.isdigit():
                return (0, int(part))
            # 非数字段逐字符比较：(小写形式, 0小写/1大写)，保证 a<A<b<B
            chars = []
            for ch in part:
                if ch.isalpha():
                    chars.append((ch.lower(), 0 if ch.islower() else 1))
                else:
                    chars.append((ch, 0))
            return (1, chars)

        return [convert(part) for part in re.split(r'(\d+)', filename) if part]

    def getpdfpath(self):
        dirpath = self.ui.outputpath.text()
        return dirpath

    def pdfname(self):
        newname = self.ui.textEdit_pdfname.text()
        return newname

    # 只收集所选文件夹「当前层」的 PDF（不递归子目录），并去重、排除输出文件
    def getFileName(self, filedir, exclude_names=None):
        exclude = {n.lower() for n in (exclude_names or []) if n}
        file_list = []
        seen = set()
        try:
            names = os.listdir(filedir)
        except OSError as e:
            self.ui.printf(f"读取文件夹失败：{e}")
            return []

        for name in names:
            if name.lower() in exclude:
                continue
            if not name.lower().endswith('.pdf'):
                continue
            full = os.path.join(filedir, name)
            if not os.path.isfile(full):
                continue
            # 按绝对路径去重，避免同一文件被加入多次
            key = os.path.normcase(os.path.abspath(full))
            if key in seen:
                continue
            seen.add(key)
            file_list.append(full)

        file_list.sort(key=self.natural_key)
        return file_list

    def _file_md5(self, path, chunk=1024 * 1024):
        h = hashlib.md5()
        with open(path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()

    # 用 PyMuPDF 逐文件、按页范围插入（避免旧版 PyPDF2 页对象串页/重复）
    def MergePDF(self, outfile):
        self.ui.printf("开始合并PDF")
        filepath = (self.getpdfpath() or '').strip()
        if not filepath:
            self.ui.printf("请先选择PDF文件夹")
            return
        filepath = os.path.normpath(filepath)
        self.ui.printf(f"PDF文件夹路径：{filepath.replace(chr(92), '/')}")

        pdf_files = self.getFileName(filepath, exclude_names=[outfile])
        if not pdf_files:
            self.ui.printf("没有可以合并的PDF文件！")
            return

        # 打印清单 + 页数；若两个不同文件名内容完全一样，给出提示
        self.ui.printf(f"待合并文件共 {len(pdf_files)} 个（按文件名排序）：")
        expected_pages = 0
        prev_md5 = None
        prev_name = None
        for i, pdf_file in enumerate(pdf_files, 1):
            name = os.path.basename(pdf_file)
            try:
                with fitz.open(pdf_file) as src:
                    pages = src.page_count
            except Exception as e:
                self.ui.printf(f"  {i}. {name} （无法读取：{e}）")
                return
            expected_pages += pages
            md5 = self._file_md5(pdf_file)
            self.ui.printf(f"  {i}. {name} （{pages}页）")
            if prev_md5 is not None and md5 == prev_md5:
                self.ui.printf(f"  注意：{name} 与 {prev_name} 文件内容完全相同（MD5一致）")
            prev_md5 = md5
            prev_name = name

        outpath = os.path.join(filepath, outfile)
        merged = fitz.open()
        try:
            for pdf_file in pdf_files:
                with fitz.open(pdf_file) as src:
                    # 显式指定页范围，每个源文件只插入一次
                    last = src.page_count - 1
                    if last >= 0:
                        merged.insert_pdf(src, from_page=0, to_page=last)
            tmp_path = outpath + '.merging.tmp'
            merged.save(tmp_path, garbage=4, deflate=True)
            merged.close()
            merged = None
            os.replace(tmp_path, outpath)

            with fitz.open(outpath) as check:
                total_pages = check.page_count
            self.ui.printf(f"各文件页数合计：{expected_pages}")
            self.ui.printf(f"合并后的总页数：{total_pages}")
            if total_pages != expected_pages:
                self.ui.printf("警告：合并后页数与合计不一致，请反馈该结果")
            self.ui.printf("PDF文件合并完成！")
            self.ui.printf(f"合并后PDF路径：{outpath.replace(chr(92), '/')}")
        except Exception as e:
            self.ui.printf(f"合并异常：{e}")
            try:
                tmp_path = outpath + '.merging.tmp'
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
        finally:
            if merged is not None:
                merged.close()

    # 合并任务
    def start_task(self):
        outfile = self.pdfname()
        if outfile is None or outfile == '':
            outfile = "合并.pdf"
        else:
            outfile = outfile.strip()
            if not outfile.lower().endswith('.pdf'):
                outfile = outfile + '.pdf'
        start = time.time()
        self.MergePDF(outfile)
        end = time.time()
        wastetime = round((end - start), 2)
        self.ui.printf(f"总耗时：{wastetime}秒.\n")

    # 使用pdf2docx将pdf转为docx
    def getpdffile(self):
        pdfpath = self.ui.pdffilepath.text()
        return pdfpath

    def pdf2word(self):
        self.ui.printf(f"开始pdf转换word...")
        pdf_file = self.getpdffile().replace('\\', '/')
        if pdf_file is None or pdf_file == '':
            self.ui.printf("请先选择pdf文件")
        else:
            try:
                # 按需导入，避免打包启动时过早加载 numpy/pdf2docx
                from pdf2docx import Converter
                docx_file = os.path.splitext(pdf_file)[0] + '.docx'
                cv = Converter(pdf_file)
                cv.convert(docx_file, start=0, end=None)
                cv.close()
                self.ui.printf(f"pdf转换word完成！")
                self.ui.printf(f"转换后word路径：{docx_file}\n")
            except Exception as e:
                self.ui.printf(f"转换异常：{e}")

    # 使用fitz将pdf转为图片
    def getpdfpath1(self):
        pdffilepath = self.ui.pdfpath.text()
        return pdffilepath

    def pdf2png(self,pdfpath, zoom_x=10.0, zoom_y=10.0, rotation_angle=0):
        self.ui.printf(f"开始pdf转图片...")
        currentpath = os.path.split(pdfpath)[0].replace('/', '\\')
        imgPath = os.path.join(currentpath, 'image\\')
        if not os.path.exists(imgPath):
            os.makedirs(imgPath)
        pdf = fitz.open(pdfpath)
        for pg in range(0, pdf.page_count):
            page = pdf[pg]
            trans = fitz.Matrix(zoom_x, zoom_y).prerotate(rotation_angle)
            pm = page.get_pixmap(matrix=trans, alpha=False)
            pm.save(imgPath+str(pg)+".png")
        pdf.close()
        self.ui.printf(f"pdf转换图片完成！")
        pngpath = imgPath.replace('\\', '/')
        self.ui.printf(f"转换后图片路径：{pngpath}\n")
    def pdf2image(self):
        pdfpath = self.getpdfpath1()
        if pdfpath is None or pdfpath == '':
            self.ui.printf("请先选择pdf文件")
        self.pdf2png(pdfpath)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = MainDialog()
    gui.show()
    sys.exit(app.exec())