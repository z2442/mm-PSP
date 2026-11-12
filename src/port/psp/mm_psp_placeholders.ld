/* Keep zero storage for pointers reconstructed from the PSP asset pack. */
SECTIONS {
    .mm_psp_placeholders : {
        KEEP(*(.rodata.mm_psp_placeholders))
        KEEP(*(.data.mm_psp_placeholders))
    }
} INSERT BEFORE .rodata;
