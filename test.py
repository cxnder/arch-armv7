#!/usr/bin/env python

test_cases_arm = [
	# r0 = (r1 & 0b11111111111111111111111111100011) | (r1 & 0b11100)
	(b'\x11\x01\xc4\xe7', 'LLIL_SET_REG(r0,LLIL_OR(LLIL_AND(LLIL_REG(r0),LLIL_CONST(4294967267)),LLIL_AND(LLIL_REG(r1),LLIL_CONST(28))))'), # bfi r0, r1, #2, #3
	# temp0 = r2*r3; r0=tmp0&0xFFFFFFFF; r1=tmp0>>32 ... LOGICAL shift since mul is unsigned
	(b'\x92\x03\x81\xe0', 'LLIL_SET_REG(temp0,LLIL_MUL(LLIL_REG(r2),LLIL_REG(r3))); LLIL_SET_REG(r0,LLIL_LOW_PART(LLIL_REG(temp0))); LLIL_SET_REG(r1,LLIL_LSR(LLIL_REG(temp0),LLIL_CONST(32)))'), # umull r0, r1, r2, r3
	# same, but ARITHMETIC shift since mul is signed
	(b'\x92\x03\xc1\xe0', 'LLIL_SET_REG(temp0,LLIL_MUL(LLIL_REG(r2),LLIL_REG(r3))); LLIL_SET_REG(r0,LLIL_LOW_PART(LLIL_REG(temp0))); LLIL_SET_REG(r1,LLIL_ASR(LLIL_REG(temp0),LLIL_CONST(32)))'), # smull r0, r1, r2, r3
	# multiply and accumulate: mla r0, r1, r2, r3 lift to r0 = r3 + (r1 * r2)
	(b'\x91\x32\x20\xe0', 'LLIL_SET_REG(r0,LLIL_ADD(LLIL_REG(r3),LLIL_MUL(LLIL_REG(r1),LLIL_REG(r2))))'), # mla r0, r1, r2, r3
	# multiply and subtract: mls r0, r1, r2, r3 lift to r0 = r3 - (r1 * r2)
	(b'\x91\x32\x60\xe0', 'LLIL_SET_REG(r0,LLIL_SUB(LLIL_REG(r3),LLIL_MUL(LLIL_REG(r1),LLIL_REG(r2))))'), # mls r0, r1, r2, r3
	# sdiv r1, r2, r3 lift to r1=r2/r3 (signed)
	(b'\x12\xf3\x11\xe7', 'LLIL_SET_REG(r1,LLIL_DIVS(LLIL_REG(r2),LLIL_REG(r3)))'), # 'sdiv r1, r2, r3'
	# udiv r1, r2, r3 lift to r1=r2/r3 (unsigned)
	(b'\x12\xf3\x31\xe7', 'LLIL_SET_REG(r1,LLIL_DIVU(LLIL_REG(r2),LLIL_REG(r3)))'), # 'udiv r1, r2, r3'
	# ubfx <dst> <src> <lsb> <width>
	# ubfx r1, r2, #4, #4 should extract b7..b4, lift to r1=(r2>>4)&0b1111
	(b'\x52\x12\xe3\xe7', 'LLIL_SET_REG(r1,LLIL_AND(LLIL_LSR(LLIL_REG(r2),LLIL_CONST(4)),LLIL_CONST(15)))'), # 'ubfx r1, r2, #4, #4'
	# ubfx r2, r3, #4, #5 should extract b8..b4, lift to r2=(r3>>4)&0b11111
	(b'\x53\x22\xe4\xe7', 'LLIL_SET_REG(r2,LLIL_AND(LLIL_LSR(LLIL_REG(r3),LLIL_CONST(4)),LLIL_CONST(31)))'), # 'ubfx r2, r3, #4, #5'
	# ubfx r3, r4, #0, #16 should extract b15..b0, lift to r3=(r4>>0)&0b1111111111111111
	# though no shift is needed, no reason to complicate the lifter as the core should see x>>0 == x
	(b'\x54\x30\xef\xe7', 'LLIL_SET_REG(r3,LLIL_AND(LLIL_LSR(LLIL_REG(r4),LLIL_CONST(0)),LLIL_CONST(65535)))'), # 'ubfx r3, r4, #0, #16'
	(b'\x00\xf0\x20\xe3', ''), # nop, gets optimized from function
]

test_cases_thumb2 = [
	# this should lift the same as its arm encoding
	(b'\x61\xf3\x84\x00', 'LLIL_SET_REG(r0,LLIL_OR(LLIL_AND(LLIL_REG(r0),LLIL_CONST(4294967267)),LLIL_AND(LLIL_REG(r1),LLIL_CONST(28))))'), # bfi r0, r1, #2, #3
	(b'\xb1\xfa\x81\xf0', 'LLIL_SET_REG(temp0,LLIL_CONST(0)); LLIL_SET_REG(temp1,LLIL_REG(r1)); LLIL_GOTO(3); LLIL_IF(LLIL_CMP_NE(LLIL_REG(temp1),LLIL_CONST(0)),4,7); LLIL_SET_REG(temp1,LLIL_LSR(LLIL_REG(temp1),LLIL_CONST(1))); LLIL_SET_REG(temp0,LLIL_ADD(LLIL_REG(temp0),LLIL_CONST(1))); LLIL_GOTO(3); LLIL_SET_REG(r0,LLIL_SUB(LLIL_CONST(32),LLIL_REG(temp0)))'), # 'clz r0, r1'
	(b'\x00\xbf', ''), # nop, gets optmized from function
]

import sys
import binaryninja
from binaryninja import core
from binaryninja import binaryview
from binaryninja import lowlevelil

def il2str(il):
	if isinstance(il, lowlevelil.LowLevelILInstruction):
		return '%s(%s)' % (il.operation.name, ','.join([il2str(o) for o in il.operands]))
	else:
		return str(il)

# TODO: make this less hacky
def instr_to_il(data, plat_name):
	platform = binaryninja.Platform[plat_name]
	# make a pretend function that returns
	bv = binaryview.BinaryView.new(data)
	bv.add_function(0, plat=platform)
	assert len(bv.functions) == 1

	result = []
	for block in bv.functions[0].low_level_il:
		for il in block:
			result.append(il2str(il))
	result = '; '.join(result)
	assert result.endswith('LLIL_UNDEF()')
	result = result[0:result.index('LLIL_UNDEF()')]
	if result.endswith('; '):
		result = result[0:-2]

	return result

def check(test_i, data, actual, expected):
	print('\t    test: %d' % test_i)
	print('\t   input: %s' % data.hex())
	print('\texpected: %s' % expected)
	print('\t  actual: %s' % actual)

	if actual != expected:
		print('MISMATCH!')
		sys.exit(-1)

if __name__ == '__main__':
	for (test_i, (data, expected)) in enumerate(test_cases_arm):
		actual = instr_to_il(data, 'linux-armv7')
		check(test_i, data, actual, expected)

	for (test_i, (data, expected)) in enumerate(test_cases_thumb2):
		actual = instr_to_il(data, 'linux-thumb2')
		check(test_i, data, actual, expected)

	print('success!')
	sys.exit(0)
