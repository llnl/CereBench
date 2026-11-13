
xp param W;
xp param H;
xp param B;
xp param K;
xp param SX;
xp param SY;
xp param WAIT_ALPHA;
xp param PROFILE_STAGES;

socket x1;
socket y1;
socket x2a;
socket x2b;
socket y2a;
socket y2b;
socket bcast [[dir=out]];

sp matrix[n=B*K];
sp xvec[n=B*K];
sp value[n=B];
sp result[n=1];
sp fold512[n=512];
sp fold256[n=256];
sp fold128[n=128];
sp fold64[n=64];
sp fold32[n=32];
sp fold16[n=16];
sp fold8[n=8];
sp fold4[n=4];
sp fold2[n=2];
sp fold1[n=1];

sp barrier_value;
sp sync_token;
sp incoming;

xp done[n=1] = {0};

xp x;
xp y;
xp coord[k=2];

xp x_rem;
xp x_group_start;
xp x_group_size;
xp x_group_id;
xp x_group_count;
xp x_local;

xp y_rem;
xp y_group_start;
xp y_group_size;
xp y_group_id;
xp y_group_count;
xp y_local;

xp debug_xphase[n=6];

xp wait_left;
xp wait_count;
xp wait_sink[n=1];

xp const timer_addr = 0x7b30;
xp const timer_control_addr = 0x7b34;

xp timerreg[3] address(timer_addr);
xp timercontrolreg[1] address(timer_control_addr);

// five 48-bit timestamps, three 16-bit words each:
// reference, GEMV start, GEMV end, reduction end, AllReduce end
xp phase_timestamps[n=15];

// optional diagnostic timestamps:
// X phase 1, X phase 2, Y phase 1, Y phase 2
xp stage_timestamps[n=12];

{
    x <- coord[0];
    y <- coord[1];

    // precompute calibrated wait iterations
    // the measured wait loop costs approximately 9 cycles
    // per iteration. Compute round(WAIT_ALPHA * distance / 9)
    // before synchronization so this division loop is untimed
    wait_left <- WAIT_ALPHA * (W + H - x - y) + 4;
    wait_count <- 0;

    while (wait_left >= 9) {
        wait_left <- wait_left - 9;
        wait_count <- wait_count + 1;
    }


    done[0] <- 0;
    timercontrolreg[0] <- 4;

    i in [0, 15) {
        phase_timestamps[i] <- 0;
    }

    i in [0, 12) {
        stage_timestamps[i] <- 0;
    }

    i in [0, B) {
        value[i] <- 0;
        result[0] <- 0;
    }

    // precompute horizontal grouping
    x_rem <- W % SX;
    x_group_start <- 0;
    x_group_size <- SX;
    x_group_id <- 0;
    x_group_count <- 0;
    x_local <- x;

    if (x_rem != 0) {
        x_group_count <- (W / SX) + 1;

        if (x < x_rem) {
            x_group_size <- x_rem;
        } else {
            x_group_start <- x_rem;
            x_group_id <- 1;
            x_local <- x - x_rem;

            while (x_local >= SX) {
                x_local <- x_local - SX;
                x_group_start <- x_group_start + SX;
                x_group_id <- x_group_id + 1;
            }
        }
    } else {
        x_group_count <- W / SX;

        while (x_local >= SX) {
            x_local <- x_local - SX;
            x_group_start <- x_group_start + SX;
            x_group_id <- x_group_id + 1;
        }
    }

    debug_xphase[0] <- x;
    debug_xphase[1] <- y;
    debug_xphase[2] <- x_group_start;
    debug_xphase[3] <- x_group_size;
    debug_xphase[4] <- x_group_id;
    debug_xphase[5] <- x_local;

    // precompute vertical grouping
    y_rem <- H % SY;
    y_group_start <- 0;
    y_group_size <- SY;
    y_group_id <- 0;
    y_group_count <- 0;
    y_local <- y;

    if (y_rem != 0) {
        y_group_count <- (H / SY) + 1;

        if (y < y_rem) {
            y_group_size <- y_rem;
        } else {
            y_group_start <- y_rem;
            y_group_id <- 1;
            y_local <- y - y_rem;

            while (y_local >= SY) {
                y_local <- y_local - SY;
                y_group_start <- y_group_start + SY;
                y_group_id <- y_group_id + 1;
            }
        }
    } else {
        y_group_count <- H / SY;

        while (y_local >= SY) {
            y_local <- y_local - SY;
            y_group_start <- y_group_start + SY;
            y_group_id <- y_group_id + 1;
        }
    }

    // ========================================================
    // PASS 0: FULL WARMUP UNFUSED DOT PRODUCT ALLREDUCE
    // ========================================================

i in [0, B) {
        value[i] <- 0;

        k in [0, K) {
            value[i] <-
                value[i] +
                matrix[i * K + k] * xvec[i * K + k];
        }
    }

// horizontal phase 1 within each SX group
    if (x_group_size > 1) {
        i in [0, B) {
            if (x_local != x_group_size - 1) {
                incoming <- x1[];
                value[i] <- value[i] + incoming;
            }

            if (x_local != 0) {
                x1[] <- value[i];
            }
        }
    }

    // horizontal phase 2 between group leaders
    if (x_local == 0) {
        if (x_group_count > 1) {
            i in [0, B) {
                if (x_group_id != x_group_count - 1) {
                    if ((x_group_id & 1) == 0) {
                        incoming <- x2a[];
                    } else {
                        incoming <- x2b[];
                    }

                    value[i] <- value[i] + incoming;
                }

                if (x_group_id != 0) {
                    if ((x_group_id & 1) == 1) {
                        x2a[] <- value[i];
                    } else {
                        x2b[] <- value[i];
                    }
                }
            }
        }
    }

    // vertical Two-Phase reduction on column zero
    if (x == 0) {
        if (y_group_size > 1) {
            i in [0, B) {
                if (y_local != y_group_size - 1) {
                    incoming <- y1[];
                    value[i] <- value[i] + incoming;
                }

                if (y_local != 0) {
                    y1[] <- value[i];
                }
            }
        }

        if (y_local == 0) {
            if (y_group_count > 1) {
                i in [0, B) {
                    if (y_group_id != y_group_count - 1) {
                        if ((y_group_id & 1) == 0) {
                            incoming <- y2a[];
                        } else {
                            incoming <- y2b[];
                        }

                        value[i] <- value[i] + incoming;
                    }

                    if (y_group_id != 0) {
                        if ((y_group_id & 1) == 1) {
                            y2a[] <- value[i];
                        } else {
                            y2b[] <- value[i];
                        }
                    }
                }
            }
        }
    }

// balanced scalar fold for every integer 1 <= B <= 1024
// odd elements are carried into the next level
if (B == 1) {
    fold1[0] <- value[0];
}

if (B > 1) {
    i in [0, (B) / 2) {
        fold512[i] <-
            value[2*i] + value[2*i + 1];
    }

    if (B % 2 != 0) {
        fold512[(B) / 2] <-
            value[B - 1];
    }

    if (B <= 2) {
        fold1[0] <- fold512[0];
    }
}

if (B > 2) {
    i in [0, ((B + 1) / 2) / 2) {
        fold256[i] <-
            fold512[2*i] + fold512[2*i + 1];
    }

    if ((((B + 1) / 2) & 1) != 0) {
        fold256[((B + 1) / 2) / 2] <-
            fold512[((B + 1) / 2) - 1];
    }

    if (B <= 4) {
        fold1[0] <- fold256[0];
    }
}

if (B > 4) {
    i in [0, ((B + 3) / 4) / 2) {
        fold128[i] <-
            fold256[2*i] + fold256[2*i + 1];
    }

    if ((((B + 3) / 4) & 1) != 0) {
        fold128[((B + 3) / 4) / 2] <-
            fold256[((B + 3) / 4) - 1];
    }

    if (B <= 8) {
        fold1[0] <- fold128[0];
    }
}

if (B > 8) {
    i in [0, ((B + 7) / 8) / 2) {
        fold64[i] <-
            fold128[2*i] + fold128[2*i + 1];
    }

    if ((((B + 7) / 8) & 1) != 0) {
        fold64[((B + 7) / 8) / 2] <-
            fold128[((B + 7) / 8) - 1];
    }

    if (B <= 16) {
        fold1[0] <- fold64[0];
    }
}

if (B > 16) {
    i in [0, ((B + 15) / 16) / 2) {
        fold32[i] <-
            fold64[2*i] + fold64[2*i + 1];
    }

    if ((((B + 15) / 16) & 1) != 0) {
        fold32[((B + 15) / 16) / 2] <-
            fold64[((B + 15) / 16) - 1];
    }

    if (B <= 32) {
        fold1[0] <- fold32[0];
    }
}

if (B > 32) {
    i in [0, ((B + 31) / 32) / 2) {
        fold16[i] <-
            fold32[2*i] + fold32[2*i + 1];
    }

    if ((((B + 31) / 32) & 1) != 0) {
        fold16[((B + 31) / 32) / 2] <-
            fold32[((B + 31) / 32) - 1];
    }

    if (B <= 64) {
        fold1[0] <- fold16[0];
    }
}

if (B > 64) {
    i in [0, ((B + 63) / 64) / 2) {
        fold8[i] <-
            fold16[2*i] + fold16[2*i + 1];
    }

    if ((((B + 63) / 64) & 1) != 0) {
        fold8[((B + 63) / 64) / 2] <-
            fold16[((B + 63) / 64) - 1];
    }

    if (B <= 128) {
        fold1[0] <- fold8[0];
    }
}

if (B > 128) {
    i in [0, ((B + 127) / 128) / 2) {
        fold4[i] <-
            fold8[2*i] + fold8[2*i + 1];
    }

    if ((((B + 127) / 128) & 1) != 0) {
        fold4[((B + 127) / 128) / 2] <-
            fold8[((B + 127) / 128) - 1];
    }

    if (B <= 256) {
        fold1[0] <- fold4[0];
    }
}

if (B > 256) {
    i in [0, ((B + 255) / 256) / 2) {
        fold2[i] <-
            fold4[2*i] + fold4[2*i + 1];
    }

    if ((((B + 255) / 256) & 1) != 0) {
        fold2[((B + 255) / 256) / 2] <-
            fold4[((B + 255) / 256) - 1];
    }

    if (B <= 512) {
        fold1[0] <- fold2[0];
    }
}

if (B > 512) {
    i in [0, ((B + 511) / 512) / 2) {
        fold1[i] <-
            fold2[2*i] + fold2[2*i + 1];
    }

    if ((((B + 511) / 512) & 1) != 0) {
        fold1[((B + 511) / 512) / 2] <-
            fold2[((B + 511) / 512) - 1];
    }
}

value[0] <- fold1[0];
result[0] <- value[0];
bcast[] <- value[0];

    // ========================================================
    // POST-WARMUP GLOBAL BARRIER
    // ========================================================

barrier_value <- 1;

    if (x_group_size > 1) {
        if (x_local != x_group_size - 1) {
            incoming <- x1[];
            barrier_value <- barrier_value + incoming;
        }

        if (x_local != 0) {
            x1[] <- barrier_value;
        }
    }

    if (x_local == 0) {
        if (x_group_count > 1) {
            if (x_group_id != x_group_count - 1) {
                if ((x_group_id & 1) == 0) {
                    incoming <- x2a[];
                } else {
                    incoming <- x2b[];
                }

                barrier_value <- barrier_value + incoming;
            }

            if (x_group_id != 0) {
                if ((x_group_id & 1) == 1) {
                    x2a[] <- barrier_value;
                } else {
                    x2b[] <- barrier_value;
                }
            }
        }
    }

    if (x == 0) {
        if (y_group_size > 1) {
            if (y_local != y_group_size - 1) {
                incoming <- y1[];
                barrier_value <- barrier_value + incoming;
            }

            if (y_local != 0) {
                y1[] <- barrier_value;
            }
        }

        if (y_local == 0) {
            if (y_group_count > 1) {
                if (y_group_id != y_group_count - 1) {
                    if ((y_group_id & 1) == 0) {
                        incoming <- y2a[];
                    } else {
                        incoming <- y2b[];
                    }

                    barrier_value <- barrier_value + incoming;
                }

                if (y_group_id != 0) {
                    if ((y_group_id & 1) == 1) {
                        y2a[] <- barrier_value;
                    } else {
                        y2b[] <- barrier_value;
                    }
                }
            }
        }
    }

phase_timestamps[0] <- timerreg[0];
    phase_timestamps[1] <- timerreg[1];
    phase_timestamps[2] <- timerreg[2];

    sync_token <- 1;
    bcast[] <- sync_token;

    // WAIT_ALPHA remains an iteration count. Its actual cycle
    // cost is measured by collect_timings.py
    wait_left <- wait_count;

    while (wait_left > 0) {
        wait_sink[0] <- wait_left;
        wait_left <- wait_left - 1;
    }

    phase_timestamps[3] <- timerreg[0];
    phase_timestamps[4] <- timerreg[1];
    phase_timestamps[5] <- timerreg[2];

    // ========================================================
    // PASS 1: MEASURED UNFUSED DOT PRODUCT ALLREDUCE
    // ========================================================
    
// produce every local lane before starting communication
i in [0, B) {
    value[i] <- 0;

    k in [0, K) {
        value[i] <-
            value[i] +
            matrix[i * K + k] *
            xvec[i * K + k];
    }
}

// start horizontal phase 1 only after all local lanes are ready
if (x_group_size > 1) {
    i in [0, B) {
        if (x_local != x_group_size - 1) {
            incoming <- x1[];
            value[i] <- value[i] + incoming;
        }

        if (x_local != 0) {
            x1[] <- value[i];
        }
    }
}


// producer computation plus horizontal phase 1 complete
phase_timestamps[6] <- timerreg[0];
phase_timestamps[7] <- timerreg[1];
phase_timestamps[8] <- timerreg[2];

if (PROFILE_STAGES != 0) {
    stage_timestamps[0] <- timerreg[0];
    stage_timestamps[1] <- timerreg[1];
    stage_timestamps[2] <- timerreg[2];
}

// horizontal phase 2 between group leaders
    if (x_local == 0) {
        if (x_group_count > 1) {
            i in [0, B) {
                if (x_group_id != x_group_count - 1) {
                    if ((x_group_id & 1) == 0) {
                        incoming <- x2a[];
                    } else {
                        incoming <- x2b[];
                    }

                    value[i] <- value[i] + incoming;
                }

                if (x_group_id != 0) {
                    if ((x_group_id & 1) == 1) {
                        x2a[] <- value[i];
                    } else {
                        x2b[] <- value[i];
                    }
                }
            }
        }
    }

    if (PROFILE_STAGES != 0) {
        stage_timestamps[3] <- timerreg[0];
        stage_timestamps[4] <- timerreg[1];
        stage_timestamps[5] <- timerreg[2];
    }

    // vertical Two-Phase reduction on column zero
    if (x == 0) {
        if (y_group_size > 1) {
            i in [0, B) {
                if (y_local != y_group_size - 1) {
                    incoming <- y1[];
                    value[i] <- value[i] + incoming;
                }

                if (y_local != 0) {
                    y1[] <- value[i];
                }
            }
        }
    }

    if (PROFILE_STAGES != 0) {
        stage_timestamps[6] <- timerreg[0];
        stage_timestamps[7] <- timerreg[1];
        stage_timestamps[8] <- timerreg[2];
    }

    if (x == 0) {
        if (y_local == 0) {
            if (y_group_count > 1) {
                i in [0, B) {
                    if (y_group_id != y_group_count - 1) {
                        if ((y_group_id & 1) == 0) {
                            incoming <- y2a[];
                        } else {
                            incoming <- y2b[];
                        }

                        value[i] <- value[i] + incoming;
                    }

                    if (y_group_id != 0) {
                        if ((y_group_id & 1) == 1) {
                            y2a[] <- value[i];
                        } else {
                            y2b[] <- value[i];
                        }
                    }
                }
            }
        }
    }

    if (PROFILE_STAGES != 0) {
        stage_timestamps[9] <- timerreg[0];
        stage_timestamps[10] <- timerreg[1];
        stage_timestamps[11] <- timerreg[2];
    }

    phase_timestamps[9] <- timerreg[0];
    phase_timestamps[10] <- timerreg[1];
    phase_timestamps[11] <- timerreg[2];

// root completion is after all B values are injected
// balanced scalar fold for every integer 1 <= B <= 1024
// odd elements are carried into the next level
if (B == 1) {
    fold1[0] <- value[0];
}

if (B > 1) {
    i in [0, (B) / 2) {
        fold512[i] <-
            value[2*i] + value[2*i + 1];
    }

    if (B % 2 != 0) {
        fold512[(B) / 2] <-
            value[B - 1];
    }

    if (B <= 2) {
        fold1[0] <- fold512[0];
    }
}

if (B > 2) {
    i in [0, ((B + 1) / 2) / 2) {
        fold256[i] <-
            fold512[2*i] + fold512[2*i + 1];
    }

    if ((((B + 1) / 2) & 1) != 0) {
        fold256[((B + 1) / 2) / 2] <-
            fold512[((B + 1) / 2) - 1];
    }

    if (B <= 4) {
        fold1[0] <- fold256[0];
    }
}

if (B > 4) {
    i in [0, ((B + 3) / 4) / 2) {
        fold128[i] <-
            fold256[2*i] + fold256[2*i + 1];
    }

    if ((((B + 3) / 4) & 1) != 0) {
        fold128[((B + 3) / 4) / 2] <-
            fold256[((B + 3) / 4) - 1];
    }

    if (B <= 8) {
        fold1[0] <- fold128[0];
    }
}

if (B > 8) {
    i in [0, ((B + 7) / 8) / 2) {
        fold64[i] <-
            fold128[2*i] + fold128[2*i + 1];
    }

    if ((((B + 7) / 8) & 1) != 0) {
        fold64[((B + 7) / 8) / 2] <-
            fold128[((B + 7) / 8) - 1];
    }

    if (B <= 16) {
        fold1[0] <- fold64[0];
    }
}

if (B > 16) {
    i in [0, ((B + 15) / 16) / 2) {
        fold32[i] <-
            fold64[2*i] + fold64[2*i + 1];
    }

    if ((((B + 15) / 16) & 1) != 0) {
        fold32[((B + 15) / 16) / 2] <-
            fold64[((B + 15) / 16) - 1];
    }

    if (B <= 32) {
        fold1[0] <- fold32[0];
    }
}

if (B > 32) {
    i in [0, ((B + 31) / 32) / 2) {
        fold16[i] <-
            fold32[2*i] + fold32[2*i + 1];
    }

    if ((((B + 31) / 32) & 1) != 0) {
        fold16[((B + 31) / 32) / 2] <-
            fold32[((B + 31) / 32) - 1];
    }

    if (B <= 64) {
        fold1[0] <- fold16[0];
    }
}

if (B > 64) {
    i in [0, ((B + 63) / 64) / 2) {
        fold8[i] <-
            fold16[2*i] + fold16[2*i + 1];
    }

    if ((((B + 63) / 64) & 1) != 0) {
        fold8[((B + 63) / 64) / 2] <-
            fold16[((B + 63) / 64) - 1];
    }

    if (B <= 128) {
        fold1[0] <- fold8[0];
    }
}

if (B > 128) {
    i in [0, ((B + 127) / 128) / 2) {
        fold4[i] <-
            fold8[2*i] + fold8[2*i + 1];
    }

    if ((((B + 127) / 128) & 1) != 0) {
        fold4[((B + 127) / 128) / 2] <-
            fold8[((B + 127) / 128) - 1];
    }

    if (B <= 256) {
        fold1[0] <- fold4[0];
    }
}

if (B > 256) {
    i in [0, ((B + 255) / 256) / 2) {
        fold2[i] <-
            fold4[2*i] + fold4[2*i + 1];
    }

    if ((((B + 255) / 256) & 1) != 0) {
        fold2[((B + 255) / 256) / 2] <-
            fold4[((B + 255) / 256) - 1];
    }

    if (B <= 512) {
        fold1[0] <- fold2[0];
    }
}

if (B > 512) {
    i in [0, ((B + 511) / 512) / 2) {
        fold1[i] <-
            fold2[2*i] + fold2[2*i + 1];
    }

    if ((((B + 511) / 512) & 1) != 0) {
        fold1[((B + 511) / 512) / 2] <-
            fold2[((B + 511) / 512) - 1];
    }
}

value[0] <- fold1[0];

result[0] <- value[0];
bcast[] <- value[0];

    phase_timestamps[12] <- timerreg[0];
    phase_timestamps[13] <- timerreg[1];
    phase_timestamps[14] <- timerreg[2];

    done[0] <- 1;
}
