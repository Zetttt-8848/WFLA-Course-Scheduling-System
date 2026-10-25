"""Run on the local machine only: python run.py [--open] [--port 5000]."""
import argparse
import multiprocessing


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=5000)
    parser.add_argument("--open",action="store_true",help="Open the local browser")
    args=parser.parse_args()
    from wfla.web import create_app
    from waitress import serve
    if args.open:
        import threading,webbrowser
        threading.Timer(1.5,lambda:webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    print(f"WFLA local website: http://127.0.0.1:{args.port}",flush=True)
    serve(create_app(),host="127.0.0.1",port=args.port,threads=4)


if __name__=="__main__":
    multiprocessing.freeze_support()
    main()
