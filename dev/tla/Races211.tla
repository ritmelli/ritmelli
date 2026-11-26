------------------------------ MODULE Races211 ------------------------------
EXTENDS Locks, TLC

CONSTANTS Qids, NoQid, StreamFailureChecksJob, AudioSwapThroughChangeQueue

VARIABLES pc, track, nextId, line, pronto, nearEnd,
          jobStatus, stream, swTr, dlSaw,
          fila, ver, virou, closing, preparando,
          prX, prVer, prLine, prTrack, taPresa, vpSeen

lockVars == <<owner, orderBroken>>
platVars == <<track, nextId, line, pronto, nearEnd>>
jobVars == <<jobStatus, stream, swTr, dlSaw>>
queueVars == <<fila, ver, virou, closing, preparando>>
localVars == <<prX, prVer, prLine, prTrack, taPresa, vpSeen>>
vars == <<pc, lockVars, platVars, jobVars, queueVars, localVars>>

Workers == {"Download", "Swap", "Stream", "Prepare", "AudioVersion"}
Procs == Workers \cup {"Mixer", "PassageWatcher"}

NoTrack == [id |-> 0, job |-> FALSE, qid |-> NoQid, ver |-> "-", path |-> "none"]
NoSwitch == [tag |-> NoQid, sai |-> 0, ver |-> "-"]
NoPronto == [qid |-> NoQid, ver |-> "-"]

Range(s) == {s[i] : i \in 1..Len(s)}
Without(s, q) == SelectSeq(s, LAMBDA y : y /= q)
Head0(s) == IF s = <<>> THEN NoQid ELSE Head(s)
Playing == track.id /= 0 /\ track.path /= "none"
Goto(p, l) == pc' = [pc EXCEPT ![p] = l]
At(p, l) == pc[p] = l
Symmetry == Permutations(Qids)

Publish(t) ==
    /\ track' = t
    /\ nextId' = nextId + 1
    /\ line' = line + 1
    /\ pronto' = NoPronto
    /\ nearEnd' = FALSE

StopPlatter ==
    /\ track' = NoTrack
    /\ line' = line + 1
    /\ pronto' = NoPronto
    /\ nearEnd' = FALSE
    /\ UNCHANGED nextId

NewSource(path) ==
    /\ track' = [track EXCEPT !.id = nextId, !.path = path]
    /\ nextId' = nextId + 1
    /\ UNCHANGED <<line, pronto, nearEnd>>

Init ==
    /\ owner = [l \in Locks |-> NoProc]
    /\ orderBroken = FALSE
    /\ pc = [p \in Procs |->
               CASE p = "Download" -> "dl_run"
                 [] p = "Swap" -> "sw_try"
                 [] p = "Stream" -> "st_wait"
                 [] p = "Prepare" -> "pr_start"
                 [] p = "AudioVersion" -> "av_start"
                 [] p = "Mixer" -> "mx"
                 [] p = "PassageWatcher" -> "pw_idle"]
    /\ track = [id |-> 1, job |-> FALSE, qid |-> NoQid, ver |-> "-", path |-> "file"]
    /\ nextId = 2
    /\ line = 0
    /\ pronto = NoPronto
    /\ nearEnd = FALSE
    /\ jobStatus = "running"
    /\ stream = "pending"
    /\ swTr = 0
    /\ dlSaw = 0
    /\ fila \in {<<q>> : q \in Qids} \cup ({<<a, b>> : a, b \in Qids} \ {<<q, q>> : q \in Qids})
    /\ ver = [q \in Qids |-> "video"]
    /\ virou = NoSwitch
    /\ closing = NoSwitch
    /\ preparando = NoQid
    /\ prX = NoQid
    /\ prVer = "-"
    /\ prLine = 0
    /\ prTrack = 0
    /\ taPresa = NoQid
    /\ vpSeen = NoSwitch

DownloadEnds ==
    /\ At("Download", "dl_run")
    /\ \/ jobStatus' = "error" /\ Goto("Download", "dl_failed")
       \/ jobStatus' = "done" /\ Goto("Download", "dl_done")
    /\ UNCHANGED <<lockVars, platVars, stream, swTr, dlSaw, queueVars, localVars>>

DownloadFailedLock ==
    /\ At("Download", "dl_failed")
    /\ Acquire("Download", "_lock")
    /\ Goto("Download", "dl_failed_stop")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

DownloadFailedStop ==
    /\ At("Download", "dl_failed_stop")
    /\ SectionThenRelease("Download", "_qlock", {"_lock"})
    /\ IF track.job /\ track.path = "none" THEN StopPlatter ELSE UNCHANGED platVars
    /\ Goto("Download", "done")
    /\ UNCHANGED <<jobVars, queueVars, localVars>>

DownloadDoneRead ==
    /\ At("Download", "dl_done")
    /\ dlSaw' = IF track.job THEN track.id ELSE 0
    /\ Goto("Download", "dl_done_swap")
    /\ UNCHANGED <<lockVars, platVars, jobStatus, stream, swTr, queueVars, localVars>>

DownloadDoneSkip ==
    /\ At("Download", "dl_done_swap")
    /\ dlSaw = 0
    /\ Goto("Download", "done")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>

DownloadDoneLock ==
    /\ At("Download", "dl_done_swap")
    /\ dlSaw /= 0
    /\ Acquire("Download", "_lock")
    /\ Goto("Download", "dl_done_file")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

DownloadDoneFile ==
    /\ At("Download", "dl_done_file")
    /\ SectionThenRelease("Download", "_qlock", {"_lock"})
    /\ IF track.id = dlSaw THEN NewSource("file") ELSE UNCHANGED platVars
    /\ Goto("Download", "done")
    /\ UNCHANGED <<jobVars, queueVars, localVars>>

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

SwapLocks ==
    /\ WithEngineTry("Swap", "sw_try", "sw_close", "sw_wait")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

CloseSwitches ==
    /\ IF virou.tag /= NoQid
       THEN fila' = Without(fila, virou.tag) /\ virou' = NoSwitch
       ELSE UNCHANGED <<fila, virou>>
    /\ pronto' = NoPronto

SwapCloses ==
    /\ At("Swap", "sw_close")
    /\ Section("Swap", "_qlock")
    /\ CloseSwitches
    /\ Goto("Swap", "sw_publish")
    /\ UNCHANGED <<track, nextId, line, nearEnd, jobVars, ver, closing, preparando, localVars>>

SwapPublishes ==
    /\ At("Swap", "sw_publish")
    /\ Section("Swap", "_qlock")
    /\ Publish([id |-> nextId, job |-> TRUE, qid |-> NoQid, ver |-> "-", path |-> "none"])
    /\ swTr' = nextId
    /\ Goto("Swap", "sw_release")
    /\ UNCHANGED <<jobStatus, stream, dlSaw, queueVars, localVars>>

SwapReleases ==
    /\ At("Swap", "sw_release")
    /\ ReleaseAll("Swap", {"fila_lock", "_lock"})
    /\ stream' = "running"
    /\ Goto("Swap", "done")
    /\ UNCHANGED <<platVars, jobStatus, swTr, dlSaw, queueVars, localVars>>

StreamTries ==
    /\ At("Stream", "st_wait")
    /\ stream = "running"
    /\ \/ track.id /= swTr /\ stream' = "gone" /\ Goto("Stream", "done")
       \/ track.id = swTr /\ Goto("Stream", "st_opened") /\ UNCHANGED stream
       \/ track.id = swTr /\ stream' = "refused" /\ Goto("Stream", "st_refused")
    /\ UNCHANGED <<lockVars, platVars, jobStatus, swTr, dlSaw, queueVars, localVars>>

StreamOpened ==
    \/ /\ At("Stream", "st_opened")
       /\ Acquire("Stream", "_lock")
       /\ Goto("Stream", "st_opened_swap")
       /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
    \/ /\ At("Stream", "st_opened_swap")
       /\ SectionThenRelease("Stream", "_qlock", {"_lock"})
       /\ IF track.id = swTr THEN NewSource("stream") ELSE UNCHANGED platVars
       /\ stream' = "ok"
       /\ Goto("Stream", "done")
       /\ UNCHANGED <<jobStatus, swTr, dlSaw, queueVars, localVars>>

StreamRefusedToday ==
    /\ ~StreamFailureChecksJob
    /\ At("Stream", "st_refused")
    /\ Goto("Stream", "done")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>

StreamRefusedChecksJob ==
    /\ StreamFailureChecksJob
    /\ \/ /\ At("Stream", "st_refused")
          /\ Acquire("Stream", "_lock")
          /\ Goto("Stream", "st_refused_stop")
          /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
       \/ /\ At("Stream", "st_refused_stop")
          /\ SectionThenRelease("Stream", "_qlock", {"_lock"})
          /\ IF track.id = swTr /\ jobStatus = "error"
             THEN StopPlatter /\ Goto("Stream", "done")
             ELSE UNCHANGED platVars /\ Goto("Stream", "st_refused_done")
          /\ UNCHANGED <<jobVars, queueVars, localVars>>
       \/ /\ At("Stream", "st_refused_done")
          /\ jobStatus /= "done"
          /\ Goto("Stream", "done")
          /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>
       \/ /\ At("Stream", "st_refused_done")
          /\ jobStatus = "done"
          /\ Acquire("Stream", "_lock")
          /\ Goto("Stream", "st_refused_file")
          /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
       \/ /\ At("Stream", "st_refused_file")
          /\ SectionThenRelease("Stream", "_qlock", {"_lock"})
          /\ IF track.id = swTr THEN NewSource("file") ELSE UNCHANGED platVars
          /\ Goto("Stream", "done")
          /\ UNCHANGED <<jobVars, queueVars, localVars>>

MixerTime ==
    /\ ~nearEnd
    /\ Playing
    /\ Section("Mixer", "_qlock")
    /\ nearEnd' = TRUE
    /\ UNCHANGED <<pc, track, nextId, line, pronto, jobVars, queueVars, localVars>>

MixerSwitches ==
    /\ pronto.qid /= NoQid
    /\ Playing
    /\ Section("Mixer", "_qlock")
    /\ virou' = [tag |-> pronto.qid, sai |-> track.id, ver |-> pronto.ver]
    /\ Publish([id |-> nextId, job |-> FALSE, qid |-> pronto.qid, ver |-> pronto.ver, path |-> "stream"])
    /\ UNCHANGED <<pc, jobVars, fila, ver, closing, preparando, localVars>>

PrepareReads ==
    /\ At("Prepare", "pr_start")
    /\ Section("Prepare", "fila_lock")
    /\ IF fila /= <<>> /\ Playing /\ pronto.qid = NoQid
       THEN /\ prX' = Head(fila) /\ prLine' = line /\ prTrack' = track.id
            /\ nearEnd' = TRUE
            /\ Goto("Prepare", "pr_mark")
       ELSE UNCHANGED <<prX, prLine, prTrack, nearEnd>> /\ Goto("Prepare", "done")
    /\ UNCHANGED <<track, nextId, line, pronto, jobVars, queueVars, prVer, taPresa, vpSeen>>

PrepareMarks ==
    /\ At("Prepare", "pr_mark")
    /\ preparando' = prX
    /\ Goto("Prepare", "pr_source")
    /\ UNCHANGED <<lockVars, platVars, jobVars, fila, ver, virou, closing, localVars>>

PrepareSource ==
    /\ At("Prepare", "pr_source")
    /\ prVer' = ver[prX]
    /\ Goto("Prepare", "pr_try")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prLine, prTrack, taPresa, vpSeen>>

PrepareLocks ==
    /\ WithEngineTry("Prepare", "pr_try", "pr_publish", "pr_wait")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

PreparePublishes ==
    /\ At("Prepare", "pr_publish")
    /\ Section("Prepare", "_qlock")
    /\ IF Head0(fila) = prX /\ virou.tag = NoQid /\ line = prLine /\ track.id = prTrack /\ pronto.qid = NoQid
       THEN pronto' = [qid |-> prX, ver |-> prVer]
       ELSE UNCHANGED pronto
    /\ Goto("Prepare", "pr_release")
    /\ UNCHANGED <<track, nextId, line, nearEnd, jobVars, queueVars, localVars>>

PrepareReleases ==
    /\ At("Prepare", "pr_release")
    /\ ReleaseAll("Prepare", {"fila_lock", "_lock"})
    /\ preparando' = NoQid
    /\ Goto("Prepare", "done")
    /\ UNCHANGED <<platVars, jobVars, fila, ver, virou, closing, localVars>>

Held1 ==
    IF fila /= <<>> /\ (nearEnd \/ pronto.qid = Head(fila) \/ preparando = Head(fila))
    THEN Head(fila)
    ELSE NoQid

ToAudio(q, keep) ==
    IF q \in Range(fila) /\ q \notin keep /\ ver[q] = "video"
    THEN ver' = [ver EXCEPT ![q] = "audio"]
    ELSE UNCHANGED ver

AudioVersionLocks ==
    /\ At("AudioVersion", "av_start")
    /\ Acquire("AudioVersion", "fila_lock")
    /\ Goto("AudioVersion", "av_held")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

AudioVersionToday ==
    /\ ~AudioSwapThroughChangeQueue
    /\ \/ /\ At("AudioVersion", "av_held")
          /\ taPresa' = Held1
          /\ Goto("AudioVersion", "av_swap")
          /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, vpSeen>>
       \/ /\ At("AudioVersion", "av_swap")
          /\ \E q \in Qids : ToAudio(q, {taPresa})
          /\ Release("AudioVersion", "fila_lock")
          /\ Goto("AudioVersion", "done")
          /\ UNCHANGED <<platVars, jobVars, fila, virou, closing, preparando, localVars>>

AudioVersionThroughChangeQueue ==
    /\ AudioSwapThroughChangeQueue
    /\ At("AudioVersion", "av_held")
    /\ SectionThenRelease("AudioVersion", "_qlock", {"fila_lock"})
    /\ \E q \in Qids : ToAudio(q, {Held1, virou.tag})
    /\ Goto("AudioVersion", "done")
    /\ UNCHANGED <<platVars, jobVars, fila, virou, closing, preparando, localVars>>

PassageWatcherSees ==
    /\ At("PassageWatcher", "pw_idle")
    /\ virou.tag /= NoQid
    /\ vpSeen' = virou
    /\ Goto("PassageWatcher", "pw_lock")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, taPresa>>

PassageWatcherLocks ==
    /\ At("PassageWatcher", "pw_lock")
    /\ Acquire("PassageWatcher", "fila_lock")
    /\ Goto("PassageWatcher", "pw_take")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

PassageWatcherTakes ==
    \/ /\ At("PassageWatcher", "pw_take")
       /\ virou = vpSeen
       /\ Section("PassageWatcher", "_qlock")
       /\ virou' = NoSwitch
       /\ closing' = vpSeen
       /\ Goto("PassageWatcher", "pw_close")
       /\ UNCHANGED <<platVars, jobVars, fila, ver, preparando, localVars>>
    \/ /\ At("PassageWatcher", "pw_take")
       /\ virou /= vpSeen
       /\ SectionThenRelease("PassageWatcher", "_qlock", {"fila_lock"})
       /\ Goto("PassageWatcher", "pw_idle")
       /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

PassageWatcherCloses ==
    /\ At("PassageWatcher", "pw_close")
    /\ SectionThenRelease("PassageWatcher", "_qlock", {"fila_lock"})
    /\ fila' = Without(fila, closing.tag)
    /\ closing' = NoSwitch
    /\ Goto("PassageWatcher", "pw_idle")
    /\ UNCHANGED <<platVars, jobVars, ver, virou, preparando, localVars>>

Quiescent ==
    /\ \A p \in Workers : pc[p] = "done"
    /\ At("PassageWatcher", "pw_idle")
    /\ virou.tag = NoQid

Step ==
    \/ DownloadEnds \/ DownloadFailedLock \/ DownloadFailedStop
    \/ DownloadDoneRead \/ DownloadDoneSkip \/ DownloadDoneLock \/ DownloadDoneFile
    \/ SwapLocks \/ SwapCloses \/ SwapPublishes \/ SwapReleases
    \/ StreamTries \/ StreamOpened \/ StreamRefusedToday \/ StreamRefusedChecksJob
    \/ MixerTime \/ MixerSwitches
    \/ PrepareReads \/ PrepareMarks \/ PrepareSource \/ PrepareLocks \/ PreparePublishes \/ PrepareReleases
    \/ AudioVersionLocks \/ AudioVersionToday \/ AudioVersionThroughChangeQueue
    \/ PassageWatcherSees \/ PassageWatcherLocks \/ PassageWatcherTakes \/ PassageWatcherCloses

Next == Step \/ (Quiescent /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ track.id \in Nat /\ track.path \in {"none", "stream", "file"}
    /\ jobStatus \in {"running", "error", "done"}
    /\ stream \in {"pending", "running", "ok", "refused", "gone"}
    /\ Range(fila) \subseteq Qids
    /\ ver \in [Qids -> {"video", "audio"}]

NoOrphanLoading ==
    Quiescent => ~(track.job /\ track.path = "none" /\ jobStatus = "error" /\ stream = "refused")

NoStaleLoading ==
    Quiescent => ~(track.job /\ track.path = "none" /\ jobStatus = "done" /\ stream = "refused")

SwitchEntryMatchesPlatter ==
    \A sw \in {virou, closing} :
        sw.tag /= NoQid /\ sw.tag \in Range(fila) => ver[sw.tag] = sw.ver

=============================================================================
