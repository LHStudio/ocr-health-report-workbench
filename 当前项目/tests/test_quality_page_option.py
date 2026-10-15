import tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
import fitz
import local_service
from nutrition_report import NutritionReportService


class QualityPageOptionTest(unittest.TestCase):
    def test_single_and_batch_share_default_off_and_explicit_on(self):
        person=dict(id='fixture',general={'姓名':'验证样例','体重':65},food_rows=[{'食物名称':'米饭','平均每次食用量':'100g','次数':'1','频率周期(请核对)':'每天'}])
        with tempfile.TemporaryDirectory() as tmp, patch.object(local_service,'NutritionReportService',side_effect=lambda:NutritionReportService(prefer_cloud=False)):
            job='quality-page-fixture'
            local_service.JOBS[job]=dict(kind='nutrition',status='completed',job_dir=Path(tmp),people=[person])
            try:
                for enabled in [False,True]:
                    flag={'include_quality_page':True} if enabled else {}
                    response=local_service.generate_nutrition_report(job,dict(person=person,format='pdf',**flag))
                    with fitz.open(response.path) as doc:
                        self.assertEqual(enabled,'OCR 换算与数据质量说明' in '\n'.join(p.get_text() for p in doc))
                    response=local_service.generate_nutrition_batch_reports(job,dict(format='pdf',**flag))
                    with zipfile.ZipFile(response.path) as z:
                        data=z.read(next(n for n in z.namelist() if n.endswith('.pdf')))
                        with fitz.open(stream=data,filetype='pdf') as doc:
                            self.assertEqual(enabled,'OCR 换算与数据质量说明' in '\n'.join(p.get_text() for p in doc))
                for func,payload in [(local_service.generate_nutrition_report,dict(person=person,format='pdf')),
                                     (local_service.generate_nutrition_batch_reports,dict(format='pdf'))]:
                    with self.assertRaises(HTTPException) as e:
                        func(job,dict(payload,include_quality_page='false'))
                    self.assertEqual(400,e.exception.status_code)
            finally:
                local_service.JOBS.pop(job,None)

if __name__=='__main__':unittest.main()
