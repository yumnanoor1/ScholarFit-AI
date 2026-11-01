import glob
import pandas as pd

for path in glob.glob("data/*.xlsx"):
    df = pd.read_excel(path)
    print("=" * 60)
    print("FILE:", path)
    print("ROWS:", len(df))
    print("COUNTRIES:", sorted(df["Country"].dropna().unique()))