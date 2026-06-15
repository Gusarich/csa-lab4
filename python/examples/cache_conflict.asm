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
    la t0, slot0
    la t1, slot1
    la t2, slot2

    lw a0, 0(t0)
    lw a1, 0(t1)
    lw a2, 0(t2)

    li a3, 'Z'
    sw a3, 0(t0)
    sw a3, 0(t1)
    sw a3, 0(t2)

    lw a0, 0(t0)
    out OUT_DATA, a0

done:
    halt

.section .data
.org 0x000400
slot0:
    .word 'C'

.org 0x000500
slot1:
    .word 'A'

.org 0x000600
slot2:
    .word 'C'
