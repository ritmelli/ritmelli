------------------------------ MODULE PassageFailure ------------------------------
EXTENDS TLC

CONSTANTS Entries, Sources, Files, NoFile, NoKey, FailureCarriesTheKey, FailureLabelledByTheHead, PrepareKeysItsPick,
          FailuresKeptTogether, PickChecksTheFailures, TakeDropsTheStaleDeck, PickMatchesByEntry, FileKeyedByPresence

Keys == [e : Entries, src : Sources, file : Files \cup {NoFile, "present"}]

Symmetry == Permutations(Entries) \cup Permutations(Sources) \cup Permutations(Files)

Label(k) == IF FileKeyedByPresence /\ k.file /= NoFile THEN [k EXCEPT !.file = "present"] ELSE k

VARIABLES head, src, shelf, failed, failedSources, busy, worker, asked, picked, carried, prepared, preparedSource,
          failure, watcher, took, tookHead, tookSrc, tookBusy, tookPronto, blockedOther, retriedTheFailure

vars == <<head, src, shelf, failed, failedSources, busy, worker, asked, picked, carried, prepared, preparedSource,
          failure, watcher, took, tookHead, tookSrc, tookBusy, tookPronto, blockedOther, retriedTheFailure>>

watcherVars == <<watcher, took, tookHead, tookSrc, tookBusy, tookPronto>>

Blocks(m, k) == IF FailureCarriesTheKey THEN k \in m ELSE \E f \in m : f.e = k.e

PickBlocks(m, c) == IF PickMatchesByEntry THEN \E f \in m : f.e = c.e ELSE Blocks(m, c)

Stored(m, k) == IF FailuresKeptTogether THEN m \cup {k} ELSE {k}

Init ==
    /\ head \in Entries
    /\ src \in [Entries -> Sources]
    /\ shelf = [e \in Entries |-> NoFile]
    /\ failed = {} /\ failedSources = {} /\ busy = FALSE /\ worker = "idle"
    /\ asked = NoKey /\ picked = NoKey /\ carried = NoKey
    /\ prepared = NoKey /\ preparedSource = NoKey /\ failure = NoKey
    /\ watcher = "idle" /\ took = NoKey /\ tookHead = head /\ tookSrc = src[head] /\ tookBusy = FALSE
    /\ tookPronto = NoKey
    /\ blockedOther = FALSE /\ retriedTheFailure = FALSE

MoveHead ==
    /\ watcher /= "taken"
    /\ \E e \in Entries : e /= head /\ head' = e
    /\ UNCHANGED <<src, shelf, failed, failedSources, busy, worker, asked, picked, carried, prepared, preparedSource,
                   failure, watcherVars, blockedOther, retriedTheFailure>>

AudioVersion ==
    /\ watcher /= "taken"
    /\ \E e \in Entries, s \in Sources : s /= src[e] /\ src' = [src EXCEPT ![e] = s]
    /\ UNCHANGED <<head, shelf, failed, failedSources, busy, worker, asked, picked, carried, prepared, preparedSource,
                   failure, watcherVars, blockedOther, retriedTheFailure>>

ShelfChanges ==
    /\ \E e \in Entries, f \in Files \cup {NoFile} : f /= shelf[e] /\ shelf' = [shelf EXCEPT ![e] = f]
    /\ UNCHANGED <<head, src, failed, failedSources, busy, worker, asked, picked, carried, prepared, preparedSource,
                   failure, watcherVars, blockedOther, retriedTheFailure>>

PollTakes ==
    LET stale == prepared /= NoKey /\ prepared.e /= head
    IN /\ watcher = "idle"
       /\ watcher' = IF TakeDropsTheStaleDeck THEN "cancelled" ELSE "taken"
       /\ took' = failure /\ failure' = NoKey
       /\ tookHead' = head /\ tookSrc' = src[head] /\ tookBusy' = busy /\ tookPronto' = prepared
       /\ IF TakeDropsTheStaleDeck /\ stale THEN prepared' = NoKey /\ preparedSource' = NoKey
          ELSE UNCHANGED <<prepared, preparedSource>>
       /\ UNCHANGED <<head, src, shelf, failed, failedSources, busy, worker, asked, picked, carried, blockedOther,
                      retriedTheFailure>>

PollCancels ==
    /\ watcher = "taken"
    /\ watcher' = "cancelled"
    /\ IF tookPronto /= NoKey /\ tookPronto.e /= tookHead THEN prepared' = NoKey /\ preparedSource' = NoKey
       ELSE UNCHANGED <<prepared, preparedSource>>
    /\ UNCHANGED <<head, src, shelf, failed, failedSources, busy, worker, asked, picked, carried, failure, took,
                   tookHead, tookSrc, tookBusy, tookPronto, blockedOther, retriedTheFailure>>

PollDecides ==
    LET a == [e |-> tookHead, src |-> tookSrc, file |-> shelf[tookHead]]
        k == Label(a)
        f == IF FailureLabelledByTheHead THEN k ELSE took
        m == IF took = NoKey THEN failed ELSE Stored(failed, f)
    IN /\ watcher = "cancelled"
       /\ watcher' = "idle"
       /\ failed' = m
       /\ IF tookBusy \/ (tookPronto /= NoKey /\ tookPronto.e = tookHead)
          THEN UNCHANGED <<busy, worker, asked, blockedOther, retriedTheFailure>>
          ELSE IF Blocks(m, k)
          THEN /\ blockedOther' = (blockedOther \/ a \notin failedSources)
               /\ UNCHANGED <<busy, worker, asked, retriedTheFailure>>
          ELSE /\ busy' = TRUE /\ worker' = "picking" /\ asked' = k
               /\ retriedTheFailure' = (retriedTheFailure \/ a \in failedSources)
               /\ UNCHANGED blockedOther
       /\ UNCHANGED <<head, src, shelf, failedSources, picked, carried, prepared, preparedSource, failure, took,
                      tookHead, tookSrc, tookBusy, tookPronto>>

Pick ==
    LET p == [asked EXCEPT !.file = shelf[asked.e]]
        c == IF PrepareKeysItsPick THEN Label(p) ELSE asked
    IN /\ worker = "picking"
       /\ picked' = p /\ carried' = c
       /\ IF PickChecksTheFailures /\ PickBlocks(failed, c)
          THEN /\ busy' = FALSE /\ worker' = "idle"
               /\ blockedOther' = (blockedOther \/ p \notin failedSources)
               /\ UNCHANGED retriedTheFailure
          ELSE /\ worker' = "picked"
               /\ retriedTheFailure' = (retriedTheFailure \/ p \in failedSources)
               /\ UNCHANGED <<busy, blockedOther>>
       /\ UNCHANGED <<head, src, shelf, failed, failedSources, asked, prepared, preparedSource, failure, watcherVars>>

FailsBeforeTheEngine ==
    /\ worker = "picked"
    /\ failed' = Stored(failed, carried) /\ failedSources' = failedSources \cup {picked}
    /\ busy' = FALSE /\ worker' = "idle"
    /\ UNCHANGED <<head, src, shelf, asked, picked, carried, prepared, preparedSource, failure, watcherVars,
                   blockedOther, retriedTheFailure>>

Publishes ==
    /\ worker = "picked"
    /\ watcher /= "taken"
    /\ IF head = asked.e /\ src[head] = asked.src /\ prepared = NoKey
       THEN prepared' = carried /\ preparedSource' = picked
       ELSE UNCHANGED <<prepared, preparedSource>>
    /\ busy' = FALSE /\ worker' = "idle"
    /\ UNCHANGED <<head, src, shelf, failed, failedSources, asked, picked, carried, failure, watcherVars,
                   blockedOther, retriedTheFailure>>

EngineFails ==
    /\ prepared /= NoKey
    /\ failure' = prepared /\ failedSources' = failedSources \cup {preparedSource}
    /\ prepared' = NoKey /\ preparedSource' = NoKey
    /\ UNCHANGED <<head, src, shelf, failed, busy, worker, asked, picked, carried, watcherVars, blockedOther,
                   retriedTheFailure>>

Next == MoveHead \/ AudioVersion \/ ShelfChanges \/ PollTakes \/ PollCancels \/ PollDecides \/ Pick
        \/ FailsBeforeTheEngine \/ Publishes \/ EngineFails

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ head \in Entries /\ src \in [Entries -> Sources] /\ shelf \in [Entries -> Files \cup {NoFile}]
    /\ failed \subseteq Keys /\ failedSources \subseteq Keys
    /\ {asked, picked, carried, prepared, preparedSource, failure, took, tookPronto} \subseteq Keys \cup {NoKey}
    /\ busy \in BOOLEAN /\ worker \in {"idle", "picking", "picked"}
    /\ watcher \in {"idle", "taken", "cancelled"} /\ tookHead \in Entries /\ tookSrc \in Sources
    /\ tookBusy \in BOOLEAN /\ blockedOther \in BOOLEAN /\ retriedTheFailure \in BOOLEAN

FailureBlocksOnlyItsPrepare == ~blockedOther

NoRetryOfTheFailedSource == ~retriedTheFailure
=============================================================================
