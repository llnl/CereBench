# Latency Heatmap
Latency Heatmap collects rountrip data for sending a 32bit integer from a controller PE to several "echo" PE's.

The mesaured instruction:
```rust
t_start[i][0] <- timerreg[0];
t_start[i][1] <- timerreg[1];
t_start[i][2] <- timerreg[2];

mp_sock[] <- hdr_out.u;
mp_sock[] <- req0.u;
mp_sock[] <- req1.u;

hdr_in.u <- mp_sock[];
resp0.u <- mp_sock[];
resp1.u <- mp_sock[];

t_stop[i][0] <- timerreg[0];
t_stop[i][1] <- timerreg[1];
t_stop[i][2] <- timerreg[2];
```


# Commands to Run and Graph output
```bash
python3 scan_workflow.py \
  --w 100 \
  --h 100 \
  --cx 50 \
  --cy 50  \
  --nprobe 16  \
  --mode full \
  --exec-mode wse \
  --done-timeout-s 9000 \
  --done-poll-s 2 \
  --wse-server http://localhost:8080 \
  --cancel-after
```

```bash
python plot_latency.py all_rtt.csv \
  --cx 10 \
  --cy 10 \
  --outdir plots \
  --prefix wafer_latency \
  --units ns \
  --freq-ghz 0.85 \
  --startup-mode zero-manhattan-median
```
