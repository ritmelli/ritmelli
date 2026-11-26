------------------------------ MODULE PassageFailure ------------------------------
EXTENDS TLC

CONSTANTS Entries, Sources, NoKey, FailureCarriesTheKey, FailureLabelledByTheHead, PrepareKeysItsPick

Keys == [e : Entries, src : Sources, file : BOOLEAN]

VARIABLES head, src, shelf, memo, busy, worker, asked, picked, carried, prepared, preparedSource, failure, last,
          blockedOther, retriedTheFailure

vars == <<head, src, shelf, memo, busy, worker, asked, picked, carried, prepared, preparedSource, failure, last,
          blockedOther, retriedTheFailure>>

Wanted(e) == [e |-> e, src |-> src[e], file |-> shelf[e]]

Blocks(m, k) == IF FailureCarriesTheKey THEN m = k ELSE m /= NoKey /\ m.e = k.e

Init ==
    /\ head \in Entries
    /\ src \in [Entries -> Sources]
    /\ shelf = [e \in Entries |-> FALSE]
    /\ memo = NoKey /\ busy = FALSE /\ worker = "idle"
    /\ asked = NoKey /\ picked = NoKey /\ carried = NoKey
    /\ prepared = NoKey /\ preparedSource = NoKey /\ failure = NoKey /\ last = NoKey
    /\ blockedOther = FALSE /\ retriedTheFailure = FALSE

MoveHead ==
    /\ \E e \in Entries : e /= head /\ head' = e
    /\ UNCHANGED <<src, shelf, memo, busy, worker, asked, picked, carried, prepared, preparedSource, failure, last,
                   blockedOther, retriedTheFailure>>

AudioVersion ==
    /\ \E e \in Entries, s \in Sources : s /= src[e] /\ src' = [src EXCEPT ![e] = s]
    /\ UNCHANGED <<head, shelf, memo, busy, worker, asked, picked, carried, prepared, preparedSource, failure, last,
                   blockedOther, retriedTheFailure>>

FileReachesTheShelf ==
    /\ \E e \in Entries : ~shelf[e] /\ shelf' = [shelf EXCEPT ![e] = TRUE]
    /\ UNCHANGED <<head, src, memo, busy, worker, asked, picked, carried, prepared, preparedSource, failure, last,
                   blockedOther, retriedTheFailure>>

Poll ==
    LET m == IF failure = NoKey THEN memo ELSE IF FailureLabelledByTheHead THEN Wanted(head) ELSE failure
        k == Wanted(head)
        holds == prepared /= NoKey /\ prepared.e = head
    IN /\ failure' = NoKey
       /\ memo' = m
       /\ IF prepared /= NoKey /\ ~holds THEN prepared' = NoKey /\ preparedSource' = NoKey
          ELSE UNCHANGED <<prepared, preparedSource>>
       /\ IF busy \/ holds THEN UNCHANGED <<busy, worker, asked, blockedOther, retriedTheFailure>>
          ELSE IF Blocks(m, k)
          THEN /\ blockedOther' = (blockedOther \/ k /= last)
               /\ UNCHANGED <<busy, worker, asked, retriedTheFailure>>
          ELSE /\ busy' = TRUE /\ worker' = "picking" /\ asked' = k
               /\ retriedTheFailure' = (retriedTheFailure \/ k = last)
               /\ UNCHANGED blockedOther
       /\ UNCHANGED <<head, src, shelf, picked, carried, last>>

Pick ==
    /\ worker = "picking"
    /\ picked' = [asked EXCEPT !.file = shelf[asked.e]]
    /\ carried' = IF PrepareKeysItsPick THEN picked' ELSE asked
    /\ worker' = "picked"
    /\ UNCHANGED <<head, src, shelf, memo, busy, asked, prepared, preparedSource, failure, last, blockedOther,
                   retriedTheFailure>>

FailsBeforeTheEngine ==
    /\ worker = "picked"
    /\ memo' = carried /\ last' = picked
    /\ busy' = FALSE /\ worker' = "idle"
    /\ UNCHANGED <<head, src, shelf, asked, picked, carried, prepared, preparedSource, failure, blockedOther,
                   retriedTheFailure>>

Publishes ==
    /\ worker = "picked"
    /\ IF head = asked.e /\ src[head] = asked.src /\ prepared = NoKey
       THEN prepared' = carried /\ preparedSource' = picked
       ELSE UNCHANGED <<prepared, preparedSource>>
    /\ busy' = FALSE /\ worker' = "idle"
    /\ UNCHANGED <<head, src, shelf, memo, asked, picked, carried, failure, last, blockedOther, retriedTheFailure>>

EngineFails ==
    /\ prepared /= NoKey
    /\ failure' = prepared /\ last' = preparedSource
    /\ prepared' = NoKey /\ preparedSource' = NoKey
    /\ UNCHANGED <<head, src, shelf, memo, busy, worker, asked, picked, carried, blockedOther, retriedTheFailure>>

Next == MoveHead \/ AudioVersion \/ FileReachesTheShelf \/ Poll \/ Pick \/ FailsBeforeTheEngine \/ Publishes
        \/ EngineFails

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ head \in Entries /\ src \in [Entries -> Sources] /\ shelf \in [Entries -> BOOLEAN]
    /\ {memo, asked, picked, carried, prepared, preparedSource, failure, last} \subseteq Keys \cup {NoKey}
    /\ busy \in BOOLEAN /\ worker \in {"idle", "picking", "picked"}
    /\ blockedOther \in BOOLEAN /\ retriedTheFailure \in BOOLEAN

FailureBlocksOnlyItsPrepare == ~blockedOther

NoRetryOfTheFailedSource == ~retriedTheFailure
=============================================================================
