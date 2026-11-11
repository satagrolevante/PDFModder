"""Compare retained PDF resources across MuPDF's binary32 number writer.

Stream programs, CMaps, dictionary keys and integer codes remain exact. Only
decimal spellings that represent the *same finite binary32 value* may differ.
This does not compare content operators or accessible/layout properties; final
glyph, typography, geometry and pixel validation remain mandatory.
"""
import math
import struct

from .clipping import _signature


def _same_values(a,b):
    if a == b:return True
    if isinstance(a,tuple) and isinstance(b,tuple):
        return len(a)==len(b) and all(_same_values(x,y) for x,y in zip(a,b))
    if (not isinstance(a,bool) and not isinstance(b,bool)
            and isinstance(a,(int,float)) and isinstance(b,(int,float))
            and (isinstance(a,float) or isinstance(b,float))
            and math.isfinite(a) and math.isfinite(b)):
        try:
            x,y=struct.pack('!f',a),struct.pack('!f',b)
            return x==y and math.isfinite(struct.unpack('!f',x)[0])
        except (OverflowError,struct.error):
            return False
    return False


def same_resource_values(before,after):
    return _same_values(_signature(before),_signature(after))
