| Benchmark | Value | Unit |
|---|---:|---|
| RK4 single trajectory | 6.41e+05 | steps/s |
| RK4 single trajectory wall time | 0.047 | s |
| RK45 wall time (rtol=atol=1e-10) | 0.306 | s |
| RK45 max \|dE/E0\| | 3.78e-07 | 1 |
| DOP853 wall time (rtol=atol=1e-10) | 0.245 | s |
| DOP853 max \|dE/E0\| | 3.35e-07 | 1 |
| RK4 max \|dE/E0\| (dt=0.004) | 8.84e-05 | 1 |
| RK4 max \|dE/E0\| (dt=0.002) | 3.7e-06 | 1 |
| RK4 max \|dE/E0\| (dt=0.001) | 1.43e-07 | 1 |
| RK4 observed order (final-state error) | 4.045 |  |
| 10-pendulum ensemble RK4 | 1.72e+05 | pendulum-steps/s |
| 100-pendulum ensemble RK4 | 1.56e+06 | pendulum-steps/s |
| 1000-pendulum ensemble RK4 | 7.81e+06 | pendulum-steps/s |
| first-flip map 200x200 (auto: 1 process) | 2.209 | s |
| first-flip map 400x400 (9 processes) | 2.417 | s |
| first-flip map 400x400 (1 process) | 8.598 | s |
| 400x400 map parallel speed-up | 3.557 | x |
| raster render 640x640 (default monochrome style, fade trail) | 102.843 | frames/s |
| GIF export 5 s @ 20 fps, 480x480 | 0.719 | s |
| MP4 export 5 s @ 30 fps, 1280x720 | 3.673 | s |
| peak traced memory: 30 s RK4 run (1/240 s output) | 0.403 | MiB |
| peak traced memory: 100-pendulum ensemble 10 s | 2.16 | MiB |

Measured on Apple M4 (10 logical CPUs, 16 GB RAM), macOS-26.5.2-arm64-arm-64bit-Mach-O; Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1, Matplotlib 3.11.2; chaos_lab 0.2.0 (commit 249277a), 2026-11-07T07:18:12+00:00. System load average at start (1/5/15 min): 3.5, 3.5, 3.5.
