.equ STACK_INIT, 0x01000000

.section .vectors
.org 0x000000
.word _start
.word 0
.space 56

.section .text
.org 0x000040
_start:
    li sp, STACK_INIT
    la t0, values
    lw t1, 0(t0)
    lw t2, 4(t0)
    lw t3, 8(t0)
    lw t4, 12(t0)
    add a0, t1, t2
    add a0, a0, t3
    add a0, a0, t4
    out OUT_DATA, a0

done:
    halt

.section .data
values:
    .word 'A', 0, 0, 0
