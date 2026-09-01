"""Only supported V5.1 runtime CLI."""
import argparse,json
from .runtime import V51Runtime,MODES
def main():
    parser=argparse.ArgumentParser();parser.add_argument("task",choices=["preflight","morning_observation","morning_pool","morning_notification","feature_freeze","confirmation","confirmation_notification","execution","next_open_exit","round_trip_acceptance","health","acceptance","provider_smoke"]);parser.add_argument("--mode",choices=sorted(MODES),default="SHADOW");parser.add_argument("--data-dir",default=None);args=parser.parse_args();runtime=V51Runtime(args.data_dir,mode=args.mode)
    result=runtime.provider.smoke(["600000"],now=runtime.now()).__dict__ if args.task=="provider_smoke" else runtime.run(args.task);print(json.dumps(result,ensure_ascii=False,indent=2,default=str));raise SystemExit(0 if result.get("passed",result.get("accepted",False)) else 1)
if __name__=="__main__":main()
