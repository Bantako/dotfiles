{ pkgs, ... }:

let
  co2read = pkgs.writers.writePython3Bin "co2read" {
    libraries = with pkgs.python3Packages; [ pyserial pandas pyarrow ];
  } ''
    import serial, time, signal, sys
    from datetime import date
    from pathlib import Path
    import pandas as pd

    DATA_DIR = Path.home() / 'co2-data'
    DATA_DIR.mkdir(exist_ok=True)

    buffer = []

    def parquet_path():
        return DATA_DIR / f"{date.today()}.parquet"

    def flush():
        if not buffer:
            return
        new_df = pd.DataFrame(buffer)
        path = parquet_path()
        if path.exists():
            df = pd.concat([pd.read_parquet(path), new_df], ignore_index=True)
        else:
            df = new_df
        df.to_parquet(path, index=False)
        print(f"  → {path.name} に {len(df)} rows", flush=True)
        buffer.clear()

    def on_exit(sig, frame):
        flush()
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_exit)
    signal.signal(signal.SIGINT, on_exit)

    with serial.Serial('/dev/ttyACM0', 115200, timeout=5) as s:
        s.dtr = True
        time.sleep(0.3)
        s.write(b'STA\r\n')
        for raw in s:
            line = raw.decode('ascii', errors='ignore').strip()
            if not line.startswith('CO2='):
                continue
            try:
                parts = dict(kv.split('=') for kv in line.split(','))
                row = {
                    'ts':     int(time.time()),
                    'device': 'ud-co2s',
                    'co2':    int(parts['CO2']),
                    'tmp':    float(parts['TMP']),
                    'hum':    float(parts['HUM']),
                }
            except Exception:
                continue
            buffer.append(row)
            print(f"CO2: {row['co2']:4d} ppm | Tmp: {row['tmp']:.1f}°C | Hum: {row['hum']:.1f}%", flush=True)
            if len(buffer) >= 60:
                flush()
  '';
in
{
  home.packages = [ co2read ];
}
