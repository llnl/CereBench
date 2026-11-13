xp param CX, CY;
socket mp_sock;

xp row_id[1] address(0x7C45);

union mp_header {
    u32 u;
    xp w[2];
};

union mp_payload {
    u32 u;
    xp w[2];
};

{
    union mp_header hdr_in;
    union mp_header hdr_out;
    union mp_payload req;
    union mp_payload resp;

    xp myy;
    xp flags;

    myy <- row_id[0];

    flags <- 0;
    if (CY < myy) {
        flags <- 0x80;
    } else {
        if (CY > myy) {
            flags <- 0x40;
        } else {
            flags <- 0x00;
        }
    }

    hdr_out.w[1] <- (CX << 4) | ((CY >> 8) & 0xF);
    hdr_out.w[0] <- ((CY & 0xFF) << 8) | flags | 1;

    forever {
        hdr_in.u <- mp_sock[];
        req.u <- mp_sock[];

        resp.w[0] <- req.w[0];
        resp.w[1] <- 0;

        mp_sock[] <- hdr_out.u;
        mp_sock[] <- resp.u;
    }
}
