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
    la a0, msg
    call puts_pstr

done:
    halt

puts_pstr:
    lw t0, 0(a0)
    addi t1, a0, 4
puts_pstr_loop:
    beq t0, zero, puts_pstr_done
    lw t2, 0(t1)
    out OUT_DATA, t2
    addi t1, t1, 4
    addi t0, t0, -1
    j puts_pstr_loop
puts_pstr_done:
    ret

.section .rodata
msg:
    .pstr "hello world\n"
