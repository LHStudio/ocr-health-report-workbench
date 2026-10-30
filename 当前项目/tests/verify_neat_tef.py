from copy import deepcopy
import math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nutrition_report.nutrition import NutritionService
from nutrition_report.energy_reference import accepted_energy_bounds,energy_calculation_lines
from nutrition_report.personal_targets import energy_bounds
s=NutritionService()
base=dict(projectType='足球',weight=60,bmrMin=1300,bmrMax=1500,gender='female',age=22,activityLevel='3',trainingPhase='training')
def calc(**kw):
    u={**base,**kw};before=deepcopy(u)
    e=s._calculate_nutrition({'米饭':100},u)[1]['energy']
    assert u==before
    return e
count=0
for sport in ['足球','篮球','体操','女足','男足','女篮','男篮']:
    for gender in ['female','male']:
        for weight in [40,60,100]:
            e=calc(projectType=sport,gender=gender,weight=weight)
            assert e['reference_type']=='tdee'
            assert e['neat_kcal']==10.5*weight
            for i,k in enumerate(['standard_min','standard_max']):
                assert math.isclose(e[k]*.91,base[['bmrMin','bmrMax'][i]]+e['training_expenditure']['net_daily_kcal'][i]+10.5*weight)
                assert math.isclose(e['tef_kcal'][i],e[k]*.09)
            assert energy_bounds(e)==accepted_energy_bounds(e)==(e['standard_min'],e['standard_max'])
            assert 'NEAT' in ''.join(energy_calculation_lines(e))
            count+=1
e=calc(trainingPlan={'weeklyMinutes':0})
assert math.isclose(e['standard_min'],(1300+630)/.91)
assert e['training_expenditure']['net_daily_kcal']==[0,0]
for kwargs in [dict(weight=''),dict(weight=float('nan')),dict(bmrMin='',bmrMax=''),dict(trainingPhase='competition'),dict(currentStatus='康复期'),dict(projectType='举重')]:
    e=calc(**kwargs)
    assert e['reference_type']!='tdee' and e['tef_kcal'] is None
    if kwargs.get('weight') == '' or isinstance(kwargs.get('weight'),float) and math.isnan(kwargs['weight']):
        assert e['neat_kcal'] is None
    else:
        assert e['neat_kcal']==630
for bmr in [dict(bmrMin=1300,bmrMax=1500),dict(bmrMin='',bmrMax='')]:
    p=dict(user={**base,**bmr},meals=[dict(name='米饭',amount=100)],resting_metabolism={'values':{'REE':1400}})
    original=deepcopy(p)
    d=s.build_report_data(p)
    assert p==original
    e=d['nutrition']['energy']
    assert e['resting_source']=='个人REE实测' and e['resting_bounds']==[1400,1400]
    assert math.isclose(e['standard_min'],(1400+432+630)/.91)
    assert math.isclose(e['standard_max'],(1400+756+630)/.91)
    assert d['user']['bmrMin']==bmr['bmrMin']
print('PASS measured REE priority with/without BMR; source preservation; missing input kept explicit')
print('PASS',count,'sport/gender/weight combinations; zero EEE; 6 missing/unsupported gates; downstream bounds; input preservation')
