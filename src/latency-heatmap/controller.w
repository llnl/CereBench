xp param NPROBE, NWARMUP, CX, CY;
socket mp_sock;

xp const tra1 = 0x7b30;
xp const tra2 = 0x7b34;
xp timerreg[3] address(tra1);
xp timercontrolreg[1] address(tra2);

xp row_id[1] address(0x7C45);

xp target_x[n=NPROBE];
xp target_y[n=NPROBE];

xp t_start[n=NPROBE];
xp t_stop[n=NPROBE];

xp send_count[1];
xp last_sent_x[1];
xp last_sent_y[1];

xp reply_x[n=NPROBE];
xp reply_y[n=NPROBE];
xp reply_seq[n=NPROBE];
xp reply_dbg_row[n=NPROBE];

xp done[1];
xp count[1];

union mp_header {
    u32 u;
    xp w[2];
};

union mp_payload {
    u32 u;
    xp w[2];
};

{
    xp i = 0;
    xp w = 0;
    xp j = 0;

    union mp_header hdr_out;
    union mp_header hdr_in;
    union mp_payload req;
    union mp_payload resp;

    xp myy;
    xp dest_x;
    xp dest_y;
    xp flags;

    timercontrolreg[0] <- 4;

    myy <- row_id[0];

    done[0] <- 0;
    count[0] <- 0;
    send_count[0] <- 0;
    last_sent_x[0] <- -1;
    last_sent_y[0] <- -1;

    if (NPROBE > 0) {
        while (w < NWARMUP) {
            j <- w;
            while (j >= NPROBE) {
                j <- j - NPROBE;
            }

            dest_x <- target_x[j];
            dest_y <- target_y[j];

            flags <- 0;
            if (dest_y < myy) {
                flags <- 0x80;
            } else {
                if (dest_y > myy) {
                    flags <- 0x40;
                } else {
                    flags <- 0x00;
                }
            }

            hdr_out.w[1] <- (dest_x << 4) | ((dest_y >> 8) & 0xF);
            hdr_out.w[0] <- ((dest_y & 0xFF) << 8) | flags | 1;

            req.w[0] <- -1;
            req.w[1] <- 0;

            last_sent_x[0] <- dest_x;
            last_sent_y[0] <- dest_y;
            send_count[0] <- w + 1;

            mp_sock[] <- hdr_out.u;
            mp_sock[] <- req.u;

            hdr_in.u <- mp_sock[];
            resp.u <- mp_sock[];

            w <- w + 1;
        }
    }

    send_count[0] <- 0;
    last_sent_x[0] <- -1;
    last_sent_y[0] <- -1;

    while (i < NPROBE) {
        dest_x <- target_x[i];
        dest_y <- target_y[i];

        flags <- 0;
        if (dest_y < myy) {
            flags <- 0x80;
        } else {
            if (dest_y > myy) {
                flags <- 0x40;
            } else {
                flags <- 0x00;
            }
        }

        hdr_out.w[1] <- (dest_x << 4) | ((dest_y >> 8) & 0xF);
        hdr_out.w[0] <- ((dest_y & 0xFF) << 8) | flags | 1;

        req.w[0] <- i;
        req.w[1] <- 0;

        last_sent_x[0] <- dest_x;
        last_sent_y[0] <- dest_y;
        send_count[0] <- i + 1;

        t_start[i] <- timerreg[0];

        mp_sock[] <- hdr_out.u;
        mp_sock[] <- req.u;

        hdr_in.u <- mp_sock[];
        resp.u <- mp_sock[];

        t_stop[i] <- timerreg[0];

        reply_seq[i] <- resp.w[0];
        reply_x[i] <- resp.w[1];
        reply_y[i] <- 0;
        reply_dbg_row[i] <- 0;

        i <- i + 1;
    }

    count[0] <- i;
    done[0] <- 1;
}
