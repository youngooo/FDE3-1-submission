"""实现 compare；不调用大模型或另建问数引擎。"""
import json,sys
def compare(expected,actual):
    raise NotImplementedError("STUDENT_JUDGE_REQUIRED")
if __name__=="__main__":
    data=json.load(sys.stdin);print(json.dumps(compare(data["expected"],data["actual"]),ensure_ascii=False))
