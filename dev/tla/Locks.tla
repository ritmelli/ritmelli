------------------------------- MODULE Locks -------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANT NoProc

VARIABLES owner, orderBroken

LockOrder == <<"fila_lock", "_lock", "_qlock">>
BeforeQlockOnly == {"proximo_lock", "lib_lock"}
AudioThread == "Mixer"
AudioLocks == {"_qlock"}

Ordered == {LockOrder[i] : i \in 1..Len(LockOrder)}
Locks == Ordered \cup BeforeQlockOnly
Rank(l) == CHOOSE i \in 1..Len(LockOrder) : LockOrder[i] = l

Held(p) == {l \in Locks : owner[l] = p}

InOrderWith(H, l) ==
    IF l \in BeforeQlockOnly
    THEN H = {}
    ELSE \A h \in H :
            \/ h \in BeforeQlockOnly /\ l = "_qlock"
            \/ h \in Ordered /\ Rank(h) < Rank(l)

MayTake(p, l) == p /= AudioThread \/ l \in AudioLocks

Takes(p, H, l) == InOrderWith(H, l) /\ MayTake(p, l)

Broken(p, a, b) == ~Takes(p, Held(p), a) \/ ~Takes(p, Held(p) \cup {a}, b)

Free(l) == owner[l] = NoProc

Acquire(p, l) ==
    /\ Free(l)
    /\ owner' = [owner EXCEPT ![l] = p]
    /\ orderBroken' = (orderBroken \/ ~Takes(p, Held(p), l))

AcquireBoth(p, a, b) ==
    /\ Free(a) /\ Free(b)
    /\ owner' = [owner EXCEPT ![a] = p, ![b] = p]
    /\ orderBroken' = (orderBroken \/ Broken(p, a, b))

Release(p, l) ==
    /\ owner[l] = p
    /\ owner' = [owner EXCEPT ![l] = NoProc]
    /\ UNCHANGED orderBroken

ReleaseAll(p, S) ==
    /\ \A l \in S : owner[l] = p
    /\ owner' = [l \in Locks |-> IF l \in S THEN NoProc ELSE owner[l]]
    /\ UNCHANGED orderBroken

Section(p, l) ==
    /\ Free(l)
    /\ UNCHANGED owner
    /\ orderBroken' = (orderBroken \/ ~Takes(p, Held(p), l))

SectionThenRelease(p, l, S) ==
    /\ Free(l)
    /\ \A x \in S : owner[x] = p
    /\ owner' = [x \in Locks |-> IF x \in S THEN NoProc ELSE owner[x]]
    /\ orderBroken' = (orderBroken \/ ~Takes(p, Held(p), l))

SectionBoth(p, a, b) ==
    /\ Free(a) /\ Free(b)
    /\ UNCHANGED owner
    /\ orderBroken' = (orderBroken \/ Broken(p, a, b))

LockOrderKept == ~orderBroken

=============================================================================
