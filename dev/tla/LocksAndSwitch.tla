---------------------------- MODULE LocksAndSwitch ----------------------------
EXTENDS Locks, Integers, TLC

CONSTANTS Qids, NoQid, Raised, RIds, GIds,
          NextsJoin, NextsJoinAfterPublish, NextResolvesItsGroup, StopClosesSwitches, StopSavesItsRecord,
          ClosingRecordsTheSwitch, FailedSwapReleasesReservation,
          QueueChangeUnderQlock, ReserveReadsProximoWithoutLock, TakingTheSwitchClearsIt, Reopens,
          PreparesAgain, ClosesTheSecondSwitch, MixerTakesOnlyQlock, PlayErrorReachesTheGroup,
          RaisingNextTakesTheResolvedResult, PlaysCanSucceed, TakenSwitchEndsTheAdvance

VARIABLES pc, s

vars == <<owner, orderBroken, pc, s>>

Nexts == {"N1", "N2"}
Workers == Nexts \cup {"StopOrChange", "Reopen", "Prepare"}
Procs == Workers \cup {"Mixer", "PassageWatcher"}

NoTrack == [id |-> 0, qid |-> NoQid]
NoSwitch == [tag |-> NoQid, sai |-> 0]
NoRes == [used |-> FALSE, line |-> 0, x |-> NoQid, tocando |-> FALSE, publicada |-> -1, feita |-> FALSE,
          entrada |-> NoQid, grupos |-> {}]
NoGroup == [used |-> FALSE, line |-> 0, r |-> 0, virada |-> FALSE, feita |-> FALSE, entrada |-> NoQid]
NoNext == [g |-> 0, vx |-> NoQid, v |-> NoSwitch, r |-> 0, em |-> 0, x |-> NoQid, old |-> 0, res |-> "unset",
           joined |-> 0]

Range(q) == {q[i] : i \in 1..Len(q)}
Without(q, x) == SelectSeq(q, LAMBDA y : y /= x)
Goto(p, l) == pc' = [pc EXCEPT ![p] = l]
At(p, l) == pc[p] = l
Symmetry == Permutations(Qids)

TwoEntries == {<<a, b>> : a, b \in Qids} \ {<<q, q>> : q \in Qids}

Init ==
    /\ owner = [l \in Locks |-> NoProc]
    /\ orderBroken = FALSE
    /\ pc = [p \in Procs |->
               CASE p \in Nexts -> "nx_start"
                 [] p = "StopOrChange" -> "sq_start"
                 [] p = "Reopen" -> IF Reopens THEN "ro_start" ELSE "done"
                 [] p = "Prepare" -> IF PreparesAgain THEN "pr_start" ELSE "done"
                 [] p = "Mixer" -> "mx"
                 [] p = "PassageWatcher" -> "pw_idle"]
    /\ \E f \in TwoEntries, p0 \in {"none", "head"} :
         s = [track |-> [id |-> 1, qid |-> NoQid], nextId |-> 2, line |-> 0,
              pronto |-> IF p0 = "head" THEN Head(f) ELSE NoQid,
              virou |-> NoSwitch, fila |-> f, history |-> <<>>, left |-> <<>>,
              res |-> [r \in RIds |-> NoRes], appRes |-> 0, nextRid |-> 1,
              grp |-> [g \in GIds |-> NoGroup], proximo |-> 0, nextGid |-> 1,
              n |-> [x \in Nexts |-> NoNext],
              overlap |-> FALSE, switched |-> <<>>, closed |-> <<>>, played |-> 0, failed |-> 0, taken |-> 0, badSwitch |-> FALSE,
              sqOld |-> 0, pwSeen |-> NoSwitch]

Viva(S, r) == ~S.res[r].feita /\ (S.res[r].tocando \/ S.res[r].line = S.line)

ResolveGroups(S, G, e) ==
    [S EXCEPT !.grp = [g \in GIds |->
        IF g \in G /\ ~S.grp[g].feita THEN [S.grp[g] EXCEPT !.feita = TRUE, !.entrada = e] ELSE S.grp[g]]]

Link(S, g, r) ==
    LET S1 == [S EXCEPT !.grp[g].r = r, !.res[r].grupos = @ \cup {g}]
    IN IF S1.res[r].feita THEN ResolveGroups(S1, {g}, S1.res[r].entrada) ELSE S1

ReleaseReservation(S, r, e) ==
    IF S.res[r].feita THEN S
    ELSE LET S1 == [S EXCEPT !.appRes = IF @ = r THEN 0 ELSE @, !.res[r].feita = TRUE, !.res[r].entrada = e]
         IN ResolveGroups(S1, S1.res[r].grupos, e)

Joins(S, g) ==
    LET G == S.grp[g]
        r == G.r
    IN IF ~NextsJoinAfterPublish
       THEN ~G.feita /\ G.line = S.line
       ELSE IF G.feita
       THEN G.entrada \notin {NoQid, Raised} /\ r /= 0 /\ S.res[r].publicada = S.line
       ELSE \/ G.line = S.line
            \/ r /= 0 /\ ((S.res[r].tocando /\ ~S.res[r].feita) \/ S.res[r].publicada = S.line)

SamePlatter(S, g) ==
    LET G == S.grp[g]
        r == G.r
    IN /\ ~(G.feita /\ G.entrada \in {NoQid, Raised})
       /\ \/ G.line = S.line
          \/ r /= 0 /\ ((S.res[r].tocando /\ ~S.res[r].feita) \/ S.res[r].publicada = S.line)

Leave(S) == IF S.track.id /= 0 THEN Append(S.left, S.track.id) ELSE S.left

Publish(S, q) ==
    [S EXCEPT !.left = Leave(S), !.track = [id |-> S.nextId, qid |-> q], !.nextId = @ + 1, !.line = @ + 1,
              !.pronto = NoQid]

StopPlatter(S) == [S EXCEPT !.left = Leave(S), !.track = NoTrack, !.line = @ + 1, !.pronto = NoQid]

SaveHistory(S, id) == IF id = 0 THEN S ELSE [S EXCEPT !.history = Append(@, id)]

FechaVirada(S, v) ==
    [S EXCEPT !.fila = Without(@, v.tag), !.history = Append(@, v.sai), !.closed = Append(@, v.sai)]

CloseSwitches(S) ==
    IF S.virou.tag = NoQid
    THEN [S EXCEPT !.pronto = NoQid]
    ELSE IF ~ClosingRecordsTheSwitch
    THEN [S EXCEPT !.virou = NoSwitch, !.pronto = NoQid]
    ELSE [FechaVirada([S EXCEPT !.virou = NoSwitch], S.virou) EXCEPT !.pronto = NoQid]

HeadOutsideSwitch(S) ==
    LET f == Without(S.fila, S.virou.tag) IN IF f = <<>> THEN NoQid ELSE Head(f)

CheckPrepared(S) == IF S.pronto /= NoQid /\ S.pronto /= HeadOutsideSwitch(S) THEN [S EXCEPT !.pronto = NoQid] ELSE S

SetN(S, p, f, v) == [S EXCEPT !.n[p] = [@ EXCEPT ![f] = v]]

WithEngineTry(p, here, body, wait) ==
    \/ /\ At(p, here)
       /\ Acquire(p, "fila_lock")
       /\ Goto(p, here \o "_engine")
    \/ /\ At(p, here \o "_engine")
       /\ Free("_lock")
       /\ Acquire(p, "_lock")
       /\ Goto(p, body)
    \/ /\ At(p, here \o "_engine")
       /\ ~Free("_lock")
       /\ Release(p, "fila_lock")
       /\ Goto(p, wait)
    \/ /\ At(p, wait)
       /\ Section(p, "_lock")
       /\ Goto(p, here)

NextStarts(p) ==
    /\ At(p, "nx_start")
    /\ SectionBoth(p, "proximo_lock", "_qlock")
    /\ LET q == s.proximo
           overlapNow == q /= 0 /\ SamePlatter(s, q)
           g == s.nextGid
           S0 == [s EXCEPT !.overlap = @ \/ overlapNow]
       IN IF NextsJoin /\ q /= 0 /\ Joins(s, q)
          THEN s' = SetN(S0, p, "joined", q) /\ Goto(p, "nx_wait_group")
          ELSE LET S1 == SetN([S0 EXCEPT !.grp[g] = [NoGroup EXCEPT !.used = TRUE, !.line = s.line],
                                         !.proximo = g, !.nextGid = @ + 1], p, "g", g)
                   r0 == s.appRes
               IN /\ s' = IF r0 /= 0 /\ Viva(s, r0) THEN Link(S1, g, r0)
                          ELSE IF s.virou.tag /= NoQid /\ s.virou.tag \in Range(s.fila)
                          THEN SetN(SetN([S1 EXCEPT !.grp[g].virada = TRUE], p, "v", s.virou), p, "vx", s.virou.tag)
                          ELSE S1
                  /\ Goto(p, "nx_dispatch")

NextDispatches(p) ==
    /\ At(p, "nx_dispatch")
    /\ UNCHANGED <<owner, orderBroken>>
    /\ LET g == s.n[p].g IN
       IF s.grp[g].r /= 0
       THEN s' = SetN(s, p, "em", s.grp[g].r) /\ Goto(p, "nx_wait_em")
       ELSE IF s.n[p].vx /= NoQid
       THEN UNCHANGED s /\ Goto(p, "nx_virada")
       ELSE UNCHANGED s /\ Goto(p, "nx_check")

NextClosesItsSwitch(p) ==
    \/ /\ At(p, "nx_virada")
       /\ Acquire(p, "fila_lock")
       /\ UNCHANGED s
       /\ Goto(p, "nx_virada_take")
    \/ /\ At(p, "nx_virada_take")
       /\ s.virou = s.n[p].v
       /\ Section(p, "_qlock")
       /\ s' = [s EXCEPT !.virou = NoSwitch]
       /\ Goto(p, "nx_virada_close")
    \/ /\ At(p, "nx_virada_take")
       /\ s.virou /= s.n[p].v
       /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
       /\ s' = SetN([s EXCEPT !.taken = @ + 1], p, "x", s.n[p].vx)
       /\ Goto(p, IF TakenSwitchEndsTheAdvance THEN "nx_finish" ELSE "nx_check")
    \/ /\ At(p, "nx_virada_close")
       /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
       /\ s' = SetN([FechaVirada(s, s.n[p].v) EXCEPT !.taken = @ + 1], p, "x", s.n[p].vx)
       /\ Goto(p, IF TakenSwitchEndsTheAdvance THEN "nx_finish" ELSE "nx_check")

NextChecksRunning(p) ==
    /\ At(p, "nx_check")
    /\ Section(p, "_qlock")
    /\ LET g == s.n[p].g
           r0 == s.appRes
       IN IF s.grp[g].r /= 0
          THEN s' = SetN(s, p, "em", s.grp[g].r) /\ Goto(p, "nx_wait_em")
          ELSE IF r0 /= 0 /\ Viva(s, r0) /\ s.res[r0].line = s.grp[g].line
          THEN s' = SetN(Link(s, g, r0), p, "em", r0) /\ Goto(p, "nx_wait_em")
          ELSE UNCHANGED s /\ Goto(p, "nx_lock")

NewReservation(S, p, g) ==
    LET r == S.nextRid
        S1 == [S EXCEPT !.res[r] = [NoRes EXCEPT !.used = TRUE, !.line = S.line, !.x = Head(S.fila)],
                        !.appRes = r, !.nextRid = @ + 1, !.pronto = NoQid]
        q == S1.proximo
        S2 == IF q /= 0 /\ q /= g /\ S1.grp[q].r = 0 /\ ~S1.grp[q].virada /\ ~S1.grp[q].feita
                 /\ S1.grp[q].line = S1.line
              THEN Link(S1, q, r) ELSE S1
    IN SetN(Link(S2, g, r), p, "r", r)

NextReserves(p) ==
    \/ /\ At(p, "nx_lock")
       /\ Acquire(p, "fila_lock")
       /\ UNCHANGED s
       /\ Goto(p, "nx_reserve")
    \/ /\ At(p, "nx_reserve")
       /\ LET g == s.n[p].g
              em == IF s.appRes /= 0 /\ Viva(s, s.appRes) THEN s.appRes ELSE 0
          IN CASE s.grp[g].r /= 0 ->
                    /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
                    /\ s' = SetN(s, p, "em", s.grp[g].r)
                    /\ Goto(p, "nx_wait_em")
               [] s.virou.tag /= NoQid ->
                    /\ Section(p, "_qlock")
                    /\ s' = SetN([s EXCEPT !.grp[g].line = s.line,
                                           !.grp[g].virada = @ \/ s.virou.tag \in Range(s.fila),
                                           !.virou = NoSwitch], p, "v", s.virou)
                    /\ Goto(p, "nx_reserve_close")
               [] s.line /= s.grp[g].line ->
                    /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
                    /\ s' = SetN(s, p, "x", NoQid)
                    /\ Goto(p, "nx_finish")
               [] em /= 0 ->
                    /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
                    /\ s' = SetN(Link(s, g, em), p, "em", em)
                    /\ Goto(p, "nx_wait_em")
               [] s.fila = <<>> ->
                    /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
                    /\ s' = SetN(ResolveGroups(s, {g}, NoQid), p, "x", NoQid)
                    /\ Goto(p, "nx_finish")
               [] OTHER ->
                    /\ Free("_qlock")
                    /\ owner' = [owner EXCEPT !["fila_lock"] = NoProc]
                    /\ orderBroken' = (orderBroken \/ ~InOrderWith(Held(p), "_qlock")
                                       \/ (~ReserveReadsProximoWithoutLock
                                           /\ ~InOrderWith(Held(p) \cup {"_qlock"}, "proximo_lock")))
                    /\ s' = NewReservation(s, p, g)
                    /\ Goto(p, "nx_play")
    \/ /\ At(p, "nx_reserve_close")
       /\ LET v == s.n[p].v
              present == v.tag \in Range(s.fila)
          IN IF present
             THEN /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
                  /\ s' = SetN(FechaVirada(s, v), p, "x", v.tag)
                  /\ Goto(p, "nx_finish")
             ELSE /\ Section(p, "_qlock")
                  /\ s' = FechaVirada(s, v)
                  /\ Goto(p, "nx_reserve")

NextWaitsReservation(p) ==
    /\ At(p, "nx_wait_em")
    /\ s.res[s.n[p].em].feita
    /\ UNCHANGED <<owner, orderBroken>>
    /\ s' = SetN(s, p, "x", s.res[s.n[p].em].entrada)
    /\ Goto(p, "nx_finish")

NextPlays(p) ==
    LET r == s.n[p].r
        x == s.res[r].x
    IN \/ /\ PlaysCanSucceed
          /\ WithEngineTry(p, "nx_play", "nx_troca", "nx_play_wait")
          /\ UNCHANGED s
       \/ /\ At(p, "nx_play")
          /\ UNCHANGED <<owner, orderBroken, s>>
          /\ Goto(p, "nx_raise_lock")
       \/ /\ At(p, "nx_raise_lock")
          /\ Acquire(p, "fila_lock")
          /\ UNCHANGED s
          /\ Goto(p, "nx_raise_release")
       \/ /\ At(p, "nx_raise_release")
          /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
          /\ LET a == s.appRes
                 S1 == IF a = 0 \/ a = r \/ s.res[a].x /= x
                       THEN CheckPrepared([s EXCEPT !.fila = Without(@, x),
                                                    !.failed = @ + IF x \in Range(s.fila) THEN 1 ELSE 0])
                       ELSE s
             IN s' = SetN(ReleaseReservation(S1, r, IF PlayErrorReachesTheGroup THEN Raised ELSE NoQid),
                          p, "x", IF RaisingNextTakesTheResolvedResult /\ s.res[r].feita THEN s.res[r].entrada ELSE Raised)
          /\ Goto(p, "nx_finish")
       \/ /\ At(p, "nx_troca")
          /\ Section(p, "_qlock")
          /\ UNCHANGED s
          /\ IF s.appRes /= r \/ s.res[r].line /= s.line \/ x \notin Range(s.fila)
             THEN Goto(p, "nx_troca_fail")
             ELSE Goto(p, "nx_troca_close")
       \/ /\ At(p, "nx_troca_close")
          /\ Section(p, "_qlock")
          /\ s' = CloseSwitches(s)
          /\ Goto(p, "nx_troca_load")
       \/ /\ At(p, "nx_troca_load")
          /\ Section(p, "_qlock")
          /\ IF x \in Range(s.fila) /\ s.res[r].line = s.line
             THEN /\ s' = Publish(SetN([s EXCEPT !.res[r].tocando = TRUE], p, "old", s.track.id), x)
                  /\ Goto(p, "nx_troca_publicada")
             ELSE UNCHANGED s /\ Goto(p, "nx_troca_fail")
       \/ /\ At(p, "nx_troca_publicada")
          /\ Section(p, "_qlock")
          /\ s' = [s EXCEPT !.res[r].publicada = s.line]
          /\ Goto(p, "nx_troca_done")
       \/ /\ At(p, "nx_troca_done")
          /\ SectionThenRelease(p, "_qlock", {"fila_lock", "_lock"})
          /\ s' = SetN([ReleaseReservation(SaveHistory([s EXCEPT !.fila = Without(@, x)], s.n[p].old), r, x)
                        EXCEPT !.played = @ + 1], p, "x", x)
          /\ Goto(p, "nx_finish")
       \/ /\ At(p, "nx_troca_fail")
          /\ ReleaseAll(p, {"fila_lock", "_lock"})
          /\ UNCHANGED s
          /\ Goto(p, "nx_troca_fail_lock")
       \/ /\ At(p, "nx_troca_fail_lock")
          /\ FailedSwapReleasesReservation
          /\ Acquire(p, "fila_lock")
          /\ UNCHANGED s
          /\ Goto(p, "nx_troca_fail_release")
       \/ /\ At(p, "nx_troca_fail_lock")
          /\ ~FailedSwapReleasesReservation
          /\ UNCHANGED <<owner, orderBroken>>
          /\ s' = SetN(s, p, "x", NoQid)
          /\ Goto(p, "nx_finish")
       \/ /\ At(p, "nx_troca_fail_release")
          /\ SectionThenRelease(p, "_qlock", {"fila_lock"})
          /\ s' = SetN(ReleaseReservation(s, r, NoQid), p, "x", NoQid)
          /\ Goto(p, "nx_finish")

NextFinishes(p) ==
    \/ /\ At(p, "nx_finish")
       /\ SectionBoth(p, "proximo_lock", "_qlock")
       /\ LET g == s.n[p].g
              S1 == IF s.proximo = g THEN [s EXCEPT !.proximo = 0] ELSE s
          IN s' = SetN(IF NextResolvesItsGroup THEN ResolveGroups(S1, {g}, s.n[p].x) ELSE S1, p, "res", s.n[p].x)
       /\ Goto(p, "done")
    \/ /\ At(p, "nx_wait_group")
       /\ s.grp[s.n[p].joined].feita
       /\ UNCHANGED <<owner, orderBroken>>
       /\ s' = SetN(s, p, "res", s.grp[s.n[p].joined].entrada)
       /\ Goto(p, "done")

NextProc(p) ==
    \/ NextStarts(p) \/ NextDispatches(p) \/ NextClosesItsSwitch(p) \/ NextChecksRunning(p)
    \/ NextReserves(p) \/ NextWaitsReservation(p) \/ NextPlays(p) \/ NextFinishes(p)

MixerProc ==
    /\ s.pronto /= NoQid
    /\ s.track.id /= 0
    /\ IF MixerTakesOnlyQlock THEN Section("Mixer", "_qlock") ELSE SectionBoth("Mixer", "_lock", "_qlock")
    /\ s' = [Publish(s, s.pronto) EXCEPT !.virou = [tag |-> s.pronto, sai |-> s.track.id],
                                         !.switched = Append(@, s.track.id),
                                         !.badSwitch = @ \/ s.pronto /= HeadOutsideSwitch(s)]
    /\ UNCHANGED pc

MoveOrRemove(S) ==
    {S.fila} \cup {Without(S.fila, q) : q \in Range(S.fila)}
    \cup (IF Len(S.fila) = 2 THEN {<<S.fila[2], S.fila[1]>>} ELSE {})

StopOrChangeProc ==
    \/ /\ At("StopOrChange", "sq_start")
       /\ UNCHANGED <<owner, orderBroken, s>>
       /\ \/ Goto("StopOrChange", "st_lock")
          \/ Goto("StopOrChange", "ch_lock")
    \/ /\ WithEngineTry("StopOrChange", "st_lock", "st_close", "st_wait")
       /\ UNCHANGED s
    \/ /\ At("StopOrChange", "st_close")
       /\ Section("StopOrChange", "_qlock")
       /\ s' = IF StopClosesSwitches THEN CloseSwitches(s) ELSE s
       /\ Goto("StopOrChange", "st_stop")
    \/ /\ At("StopOrChange", "st_stop")
       /\ Section("StopOrChange", "_qlock")
       /\ s' = [StopPlatter(s) EXCEPT !.sqOld = s.track.id]
       /\ Goto("StopOrChange", "st_after")
    \/ /\ At("StopOrChange", "st_after")
       /\ SectionThenRelease("StopOrChange", "_qlock", {"fila_lock", "_lock"})
       /\ s' = SaveHistory(IF s.appRes /= 0 THEN ReleaseReservation(s, s.appRes, NoQid) ELSE s,
                          IF StopSavesItsRecord THEN s.sqOld ELSE 0)
       /\ Goto("StopOrChange", "done")
    \/ /\ At("StopOrChange", "ch_lock")
       /\ Acquire("StopOrChange", "fila_lock")
       /\ UNCHANGED s
       /\ Goto("StopOrChange", "ch_change")
    \/ /\ At("StopOrChange", "ch_change")
       /\ QueueChangeUnderQlock
       /\ SectionThenRelease("StopOrChange", "_qlock", {"fila_lock"})
       /\ \E f \in MoveOrRemove(s) : s' = CheckPrepared([s EXCEPT !.fila = f])
       /\ Goto("StopOrChange", "done")
    \/ /\ At("StopOrChange", "ch_change")
       /\ ~QueueChangeUnderQlock
       /\ UNCHANGED <<owner, orderBroken>>
       /\ \E f \in MoveOrRemove(s) : s' = [s EXCEPT !.fila = f]
       /\ Goto("StopOrChange", "ch_check")
    \/ /\ At("StopOrChange", "ch_check")
       /\ SectionThenRelease("StopOrChange", "_qlock", {"fila_lock"})
       /\ s' = CheckPrepared(s)
       /\ Goto("StopOrChange", "done")

PassageWatcherProc ==
    \/ /\ At("PassageWatcher", "pw_idle")
       /\ s.virou.tag /= NoQid
       /\ UNCHANGED <<owner, orderBroken>>
       /\ s' = [s EXCEPT !.pwSeen = s.virou]
       /\ Goto("PassageWatcher", "pw_lock")
    \/ /\ At("PassageWatcher", "pw_lock")
       /\ Acquire("PassageWatcher", "fila_lock")
       /\ UNCHANGED s
       /\ Goto("PassageWatcher", "pw_take")
    \/ /\ At("PassageWatcher", "pw_take")
       /\ s.virou = s.pwSeen
       /\ Section("PassageWatcher", "_qlock")
       /\ s' = IF TakingTheSwitchClearsIt THEN [s EXCEPT !.virou = NoSwitch] ELSE s
       /\ Goto("PassageWatcher", "pw_close")
    \/ /\ At("PassageWatcher", "pw_take")
       /\ s.virou /= s.pwSeen
       /\ SectionThenRelease("PassageWatcher", "_qlock", {"fila_lock"})
       /\ UNCHANGED s
       /\ Goto("PassageWatcher", "pw_idle")
    \/ /\ At("PassageWatcher", "pw_close")
       /\ SectionThenRelease("PassageWatcher", "_qlock", {"fila_lock"})
       /\ s' = IF ClosesTheSecondSwitch \/ s.closed = <<>> THEN FechaVirada(s, s.pwSeen) ELSE s
       /\ Goto("PassageWatcher", "pw_idle")

PrepareProc ==
    \/ /\ WithEngineTry("Prepare", "pr_start", "pr_publish", "pr_wait")
       /\ UNCHANGED s
    \/ /\ At("Prepare", "pr_publish")
       /\ SectionThenRelease("Prepare", "_qlock", {"fila_lock", "_lock"})
       /\ s' = IF /\ s.pronto = NoQid /\ s.virou.tag = NoQid /\ s.track.id /= 0 /\ s.fila /= <<>>
                  /\ (s.appRes = 0 \/ ~Viva(s, s.appRes))
               THEN [s EXCEPT !.pronto = Head(s.fila)]
               ELSE s
       /\ Goto("Prepare", "done")

ReopenProc ==
    \/ /\ At("Reopen", "ro_start")
       /\ Acquire("Reopen", "_lock")
       /\ UNCHANGED s
       /\ Goto("Reopen", "ro_hold")
    \/ /\ At("Reopen", "ro_hold")
       /\ Release("Reopen", "_lock")
       /\ UNCHANGED s
       /\ Goto("Reopen", "done")

Proc(p) ==
    CASE p \in Nexts -> NextProc(p)
      [] p = "Mixer" -> MixerProc
      [] p = "StopOrChange" -> StopOrChangeProc
      [] p = "PassageWatcher" -> PassageWatcherProc
      [] p = "Reopen" -> ReopenProc
      [] p = "Prepare" -> PrepareProc

Quiescent ==
    /\ \A p \in Workers : pc[p] = "done"
    /\ At("PassageWatcher", "pw_idle")
    /\ s.virou.tag = NoQid

Next ==
    \/ \E p \in Nexts :
          \/ NextStarts(p) \/ NextDispatches(p) \/ NextClosesItsSwitch(p) \/ NextChecksRunning(p)
          \/ NextReserves(p) \/ NextWaitsReservation(p) \/ NextPlays(p) \/ NextFinishes(p)
    \/ MixerProc \/ StopOrChangeProc \/ PassageWatcherProc \/ ReopenProc \/ PrepareProc
    \/ Quiescent /\ UNCHANGED vars

Spec == Init /\ [][Next]_vars

FairSpec == Spec /\ \A p \in Procs : WF_vars(Proc(p))

TypeOK ==
    /\ pc \in [Procs -> STRING]
    /\ Range(s.fila) \subseteq Qids
    /\ s.appRes \in RIds \cup {0}
    /\ s.proximo \in GIds \cup {0}
    /\ s.nextRid \in 1..(Cardinality(RIds) + 1)
    /\ s.nextGid \in 1..(Cardinality(GIds) + 1)

SwitchOnlyToHead == ~s.badSwitch

SwitchClosesOnce ==
    /\ \A i, j \in 1..Len(s.closed) : i /= j => s.closed[i] /= s.closed[j]
    /\ Range(s.closed) \subseteq Range(s.switched)
    /\ Quiescent => Range(s.closed) = Range(s.switched)

SameResult == Quiescent /\ s.overlap => s.n["N1"].res = s.n["N2"].res

OneRemoval == Quiescent /\ s.overlap => s.played + s.failed + s.taken <= 1

OneAdvance == SameResult /\ OneRemoval

Pos(q, x) == CHOOSE k \in 1..Len(q) : q[k] = x

HistoryOnceInOrder ==
    /\ \A i \in 1..Len(s.history) : s.history[i] \in Range(s.left)
    /\ \A i, j \in 1..Len(s.history) : i < j => Pos(s.left, s.history[i]) < Pos(s.left, s.history[j])
    /\ Quiescent => s.history = s.left

ReservationsResolve == \A r \in RIds : s.res[r].used ~> s.res[r].feita

QuiescentReservationsResolved == Quiescent => \A r \in RIds : s.res[r].used => s.res[r].feita

=============================================================================
