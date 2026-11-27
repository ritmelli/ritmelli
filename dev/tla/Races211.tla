------------------------------ MODULE Races211 ------------------------------
EXTENDS Locks, TLC

CONSTANTS Qids, NoQid, StreamFailureChecksJob, AudioSwapThroughChangeQueue, StreamChecksItsTrack,
          RefusedStreamStopsWithoutTheFile, RefusedStreamTriesTheFileFirst, PrepareChecksTheVersion,
          SilentStreamGoesToTheApp, WithTheJob, WithTheMoves, AudioVersionKeepsTheReservation,
          FileSwapStartsItsReader, TwoMoves, WithThePlay, WithTheSeek, StreamRefusalChecksItsWait,
          OpenedStreamLooksForTheFile, SeekStartsANewLine, WaitKeyedByGen, WithTheForget,
          WithTheDrop, WithTheJobSwitch, DownloadEndsBeforeTheSourcePick, PrepareLooksAtTheShelf,
          PassageFileKeepsTheJob, WithTheRename, RenameReplacesTheTrack, RenameReachesThePreparedDeck,
          RecordBuiltUnderTheLock, WithTheJobOnThePlatter, TheJobIsPlayedBeforeItsDownloadEnds,
          DownloadOutcomes, StreamReaderStartsWith, QueueLengths, WithTheOtherOnTheShelf, WithTheCleanEnd,
          TheEndKeepsThePrepared, WithTheRedownload, RefusedStreamTriesTheFileAgain

VARIABLES pc, track, nextId, line, pronto, nearEnd, noReader, gen,
          jobStatus, shelf, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying,
          fila, ver, virou, closing, preparando,
          prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer,
          shelfName, dlName, prName, plName, stName, srName

lockVars == <<owner, orderBroken>>
platVars == <<track, nextId, line, pronto, nearEnd, noReader, gen>>
jobVars == <<jobStatus, shelf, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, shelfName, dlName>>
queueVars == <<fila, ver, virou, closing, preparando>>
localVars == <<prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer,
               prName, plName, stName, srName>>
vars == <<pc, lockVars, platVars, jobVars, queueVars, localVars>>

Workers == {"Download", "Swap", "Stream", "Prepare", "AudioVersion", "Play", "Forget", "Move", "Reserve", "Seek", "StreamReader",
            "Rename"}
Procs == Workers \cup {"Mixer", "PassageWatcher"}

NoTrack == [id |-> 0, job |-> FALSE, qid |-> NoQid, ver |-> "-", path |-> "none", rec |-> FALSE, name |-> 0]
NoSwitch == [tag |-> NoQid, sai |-> 0, ver |-> "-", kept |-> FALSE]
NoPronto == [qid |-> NoQid, ver |-> "-", job |-> FALSE, path |-> "stream", rec |-> FALSE, name |-> 0, kept |-> FALSE]

Range(s) == {s[i] : i \in 1..Len(s)}
Without(s, q) == SelectSeq(s, LAMBDA y : y /= q)
Head0(s) == IF s = <<>> THEN NoQid ELSE Head(s)
Playing == track.id /= 0 /\ track.path /= "none"
Goto(p, l) == pc' = [pc EXCEPT ![p] = l]
At(p, l) == pc[p] = l
Symmetry == Permutations(Qids)

FileReady == jobStatus = "done" /\ shelf

Publish(t) ==
    /\ track' = t
    /\ nextId' = nextId + 1
    /\ line' = line + 1
    /\ pronto' = NoPronto
    /\ nearEnd' = FALSE
    /\ noReader' = FALSE
    /\ UNCHANGED gen

StopPlatter ==
    /\ track' = NoTrack
    /\ line' = line + 1
    /\ pronto' = NoPronto
    /\ nearEnd' = FALSE
    /\ noReader' = FALSE
    /\ UNCHANGED <<nextId, gen>>

TheEnd == stream = "ended" /\ track.id = swTr /\ gen = stGen

NewSourceWith(path, without, name) ==
    /\ track' = [track EXCEPT !.id = nextId, !.path = path, !.job = track.job /\ path /= "file", !.name = name]
    /\ nextId' = nextId + 1
    /\ pronto' = CASE path /= "file" -> pronto
                   [] TheEnd /\ TheEndKeepsThePrepared /\ pronto.qid /= NoQid -> [pronto EXCEPT !.kept = TRUE]
                   [] OTHER -> NoPronto
    /\ noReader' = without
    /\ UNCHANGED <<line, nearEnd, gen>>

FileHandoverNamed(name) == NewSourceWith("file", (track.path = "stream" /\ ~FileSwapStartsItsReader) \/ noReader, name)

Init ==
    /\ owner = [l \in Locks |-> NoProc]
    /\ orderBroken = FALSE
    /\ pc = [p \in Procs |->
               CASE p \in {"Download", "Swap", "Stream", "StreamReader", "Forget"} /\ ~WithTheJob -> "done"
                 [] p \in {"Move", "Reserve"} /\ ~WithTheMoves -> "done"
                 [] p \in {"Play", "Reserve"} /\ ~WithThePlay -> "done"
                 [] p = "Forget" /\ ~WithTheForget -> "done"
                 [] p = "Seek" /\ ~WithTheSeek -> "done"
                 [] p \in {"Swap", "Stream", "StreamReader"} /\ ~WithTheJobOnThePlatter -> "done"
                 [] p = "Rename" -> IF WithTheRename THEN "rn_shelf" ELSE "done"
                 [] p = "Reserve" -> "rs_take"
                 [] p = "Seek" -> "sk_lock"
                 [] p = "Download" -> "dl_run"
                 [] p = "Swap" -> "sw_choose"
                 [] p = "Stream" -> "st_wait"
                 [] p = "StreamReader" -> "sr_idle"
                 [] p = "Prepare" -> "pr_start"
                 [] p = "AudioVersion" -> "av_start"
                 [] p = "Play" -> "pl_try"
                 [] p = "Forget" -> "fg_start"
                 [] p = "Move" -> "mv_swap1"
                 [] p = "Mixer" -> "mx"
                 [] p = "PassageWatcher" -> "pw_idle"]
    /\ track = [id |-> 1, job |-> FALSE, qid |-> NoQid, ver |-> "-", path |-> "file", rec |-> FALSE, name |-> 0]
    /\ nextId = 2
    /\ line = 0
    /\ pronto = NoPronto
    /\ nearEnd = FALSE
    /\ noReader = FALSE
    /\ gen = 0
    /\ jobStatus = "running"
    /\ shelf = FALSE
    /\ wrongTrack = FALSE
    /\ stream = "pending"
    /\ swTr = 0
    /\ dlSaw = 0
    /\ fileWait = <<0, 0>>
    /\ stGen = 0
    /\ refusedPlaying = FALSE
    /\ fila \in (IF 1 \in QueueLengths THEN {<<q>> : q \in Qids} ELSE {})
               \cup (IF 2 \in QueueLengths THEN {<<a, b>> : a, b \in Qids} \ {<<q, q>> : q \in Qids} ELSE {})
    /\ ver = [q \in Qids |-> "video"]
    /\ virou = NoSwitch
    /\ closing = NoSwitch
    /\ preparando = NoQid
    /\ prX = NoQid
    /\ prVer = "-"
    /\ prLine = 0
    /\ prTrack = 0
    /\ prGen = 0
    /\ prJob = FALSE
    /\ prPath = "stream"
    /\ stalePrepared = FALSE
    /\ keptHead = NoQid
    /\ resQ = NoQid
    /\ resVer = "-"
    /\ pwSeen = NoSwitch
    /\ shelfName = 0
    /\ dlName = 0
    /\ prName = 0
    /\ plName = 0
    /\ stName = 0
    /\ srName = 0

DownloadEnds ==
    /\ At("Download", "dl_run")
    /\ TheJobIsPlayedBeforeItsDownloadEnds => pc["Swap"] \in {"sw_release", "done"}
    /\ \/ "error" \in DownloadOutcomes /\ jobStatus' = "error" /\ UNCHANGED shelf /\ Goto("Download", "dl_failed")
       \/ "shelved" \in DownloadOutcomes /\ UNCHANGED jobStatus /\ shelf' = TRUE /\ Goto("Download", "dl_shelved")
    /\ UNCHANGED <<lockVars, platVars, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

DownloadMarksDone ==
    /\ At("Download", "dl_shelved")
    /\ jobStatus' = "done"
    /\ Goto("Download", "dl_done")
    /\ UNCHANGED <<lockVars, platVars, shelf, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

DownloadFailedLock ==
    /\ At("Download", "dl_failed")
    /\ Acquire("Download", "_lock")
    /\ Goto("Download", "dl_failed_stop")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

DownloadFailedStop ==
    /\ At("Download", "dl_failed_stop")
    /\ SectionThenRelease("Download", "_qlock", {"_lock"})
    /\ IF track.job /\ (track.path = "none" \/ fileWait = <<track.id, gen>>) THEN StopPlatter ELSE UNCHANGED platVars
    /\ Goto("Download", "done")
    /\ UNCHANGED <<jobVars, queueVars, localVars>>

DownloadDoneRead ==
    /\ At("Download", "dl_done")
    /\ dlSaw' = IF track.job THEN track.id ELSE 0
    /\ dlName' = shelfName
    /\ Goto("Download", "dl_done_swap")
    /\ UNCHANGED <<lockVars, platVars, jobStatus, shelf, stream, swTr, wrongTrack, fileWait, stGen, refusedPlaying, shelfName,
                   queueVars, localVars>>

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
    /\ IF track.id = dlSaw
       THEN FileHandoverNamed(IF RecordBuiltUnderTheLock THEN shelfName ELSE dlName)
       ELSE UNCHANGED platVars
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

SwapChooses ==
    /\ At("Swap", "sw_choose")
    /\ IF shelf
       THEN pc' = [pc EXCEPT !["Swap"] = "sw_file_try", !["Stream"] = "done", !["StreamReader"] = "done"]
       ELSE Goto("Swap", "sw_try")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>

SwapLocks ==
    /\ WithEngineTry("Swap", "sw_try", "sw_close", "sw_wait")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

CloseSwitches ==
    /\ IF virou.tag /= NoQid
       THEN fila' = Without(fila, virou.tag) /\ virou' = NoSwitch
       ELSE UNCHANGED <<fila, virou>>
    /\ pronto' = NoPronto

SwapFileLocks ==
    /\ WithEngineTry("Swap", "sw_file_try", "sw_file", "sw_file_wait")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

SwapPublishesTheFile ==
    /\ At("Swap", "sw_file")
    /\ SectionThenRelease("Swap", "_qlock", {"fila_lock", "_lock"})
    /\ CloseSwitches
    /\ Publish([id |-> nextId, job |-> FALSE, qid |-> NoQid, ver |-> "-", path |-> "file", rec |-> TRUE, name |-> shelfName])
    /\ swTr' = nextId
    /\ Goto("Swap", "done")
    /\ UNCHANGED <<jobStatus, shelf, stream, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, ver, closing, preparando,
                   localVars, shelfName, dlName>>

SwapCloses ==
    /\ At("Swap", "sw_close")
    /\ Section("Swap", "_qlock")
    /\ CloseSwitches
    /\ Goto("Swap", "sw_publish")
    /\ UNCHANGED <<track, nextId, line, noReader, gen, nearEnd, jobVars, ver, closing, preparando, localVars>>

SwapPublishes ==
    /\ At("Swap", "sw_publish")
    /\ Section("Swap", "_qlock")
    /\ Publish([id |-> nextId, job |-> TRUE, qid |-> NoQid, ver |-> "-", path |-> "none", rec |-> TRUE, name |-> 0])
    /\ swTr' = nextId
    /\ Goto("Swap", "sw_release")
    /\ UNCHANGED <<jobStatus, shelf, stream, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

SwapReleases ==
    /\ At("Swap", "sw_release")
    /\ ReleaseAll("Swap", {"fila_lock", "_lock"})
    /\ stream' = "running"
    /\ Goto("Swap", "done")
    /\ UNCHANGED <<platVars, jobStatus, shelf, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

StreamTries ==
    /\ At("Stream", "st_wait")
    /\ stream = "running"
    /\ \/ track.id /= swTr /\ stream' = "gone" /\ Goto("Stream", "done")
       \/ track.id = swTr /\ Goto("Stream", "st_opened") /\ UNCHANGED stream
       \/ track.id = swTr /\ stream' = "refused" /\ Goto("Stream", "done")
    /\ stName' = IF track.id = swTr THEN track.name ELSE stName
    /\ UNCHANGED <<lockVars, platVars, jobStatus, shelf, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer, prName, plName, shelfName, dlName, srName>>

StreamOpened ==
    \/ /\ At("Stream", "st_opened")
       /\ Acquire("Stream", "_lock")
       /\ Goto("Stream", "st_opened_swap")
       /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
    \/ /\ At("Stream", "st_opened_swap")
       /\ SectionThenRelease("Stream", "_qlock", {"_lock"})
       /\ IF track.id = swTr
          THEN NewSourceWith("stream", FALSE, stName) /\ swTr' = nextId /\ Goto("Stream", "st_after")
          ELSE UNCHANGED <<platVars, swTr, shelfName, dlName>> /\ Goto("Stream", "done")
       /\ stream' = "ok"
       /\ stGen' = gen
       /\ UNCHANGED <<jobStatus, shelf, dlSaw, wrongTrack, fileWait, refusedPlaying, queueVars, localVars, shelfName, dlName>>
    \/ /\ At("Stream", "st_after")
       /\ IF OpenedStreamLooksForTheFile /\ FileReady
          THEN Goto("Stream", "st_open_file_lock")
          ELSE Goto("Stream", "done")
       /\ stName' = IF OpenedStreamLooksForTheFile /\ FileReady THEN shelfName ELSE stName
       /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer, prName, plName, srName>>
    \/ /\ At("Stream", "st_open_file_lock")
       /\ Acquire("Stream", "_lock")
       /\ Goto("Stream", "st_open_file")
       /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
    \/ /\ At("Stream", "st_open_file")
       /\ SectionThenRelease("Stream", "_qlock", {"_lock"})
       /\ IF track.id = swTr THEN FileHandoverNamed(IF RecordBuiltUnderTheLock THEN shelfName ELSE stName)
          ELSE UNCHANGED platVars
       /\ Goto("Stream", "done")
       /\ UNCHANGED <<jobVars, queueVars, localVars>>
    \/ /\ At("StreamReader", "st_reading")
       /\ Section("StreamReader", "_qlock")
       /\ IF track.id = swTr /\ gen = stGen
          THEN /\ fileWait' = <<track.id, gen>> /\ stream' = "silent"
               /\ Goto("StreamReader", IF SilentStreamGoesToTheApp THEN "st_refused" ELSE "done")
          ELSE UNCHANGED <<fileWait, stream, shelfName, dlName>> /\ Goto("StreamReader", "done")
       /\ UNCHANGED <<platVars, jobStatus, shelf, swTr, dlSaw, wrongTrack, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

StreamReaderStarts ==
    /\ At("StreamReader", "sr_idle")
    /\ \/ stream = "refused" /\ Goto("StreamReader", "st_refused")
       \/ /\ stream = "ok"
          /\ \E l \in StreamReaderStartsWith \cup (IF WithTheDrop THEN {"sr_dropped"} ELSE {})
                   \cup (IF WithTheCleanEnd THEN {"sr_ended"} ELSE {}) :
                Goto("StreamReader", l)
       \/ stream = "gone" /\ Goto("StreamReader", "done")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>

StreamReaderEnds ==
    /\ At("StreamReader", "sr_dropped")
    /\ Section("StreamReader", "_qlock")
    /\ noReader' = (noReader \/ (track.id = swTr /\ gen = stGen))
    /\ stream' = IF track.id = swTr /\ gen = stGen THEN "ended" ELSE stream
    /\ Goto("StreamReader", "done")
    /\ UNCHANGED <<track, nextId, line, pronto, nearEnd, gen, jobStatus, shelf, swTr, dlSaw, wrongTrack, fileWait, stGen,
                   refusedPlaying, shelfName, dlName, queueVars, localVars>>

StreamReaderReachesItsEnd ==
    /\ At("StreamReader", "sr_ended")
    /\ Section("StreamReader", "_qlock")
    /\ stream' = IF track.id = swTr /\ gen = stGen THEN "ended" ELSE stream
    /\ Goto("StreamReader", "done")
    /\ UNCHANGED <<platVars, jobStatus, shelf, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, shelfName, dlName,
                   queueVars, localVars>>

StreamRefusedToday ==
    /\ ~StreamFailureChecksJob
    /\ At("StreamReader", "st_refused")
    /\ Goto("StreamReader", "done")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>

ActsOn(cond) == (track.id = swTr \/ ~StreamChecksItsTrack) /\ cond

Flags == wrongTrack' = (wrongTrack \/ track.id /= swTr)


WaitHolds == IF WaitKeyedByGen THEN fileWait = <<track.id, gen>> ELSE fileWait[1] = track.id

Waits == stream = "silent" /\ StreamRefusalChecksItsWait => WaitHolds

Refuses == refusedPlaying' = (refusedPlaying \/ (stream = "silent" /\ gen /= stGen))

StreamRefusedChecksJob ==
    /\ StreamFailureChecksJob
    /\ \/ /\ At("StreamReader", "st_refused")
          /\ Goto("StreamReader", IF RefusedStreamTriesTheFileFirst /\ FileReady THEN "st_file_lock" ELSE "st_stop_lock")
          /\ srName' = IF RefusedStreamTriesTheFileFirst /\ FileReady THEN shelfName ELSE srName
          /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer, prName, plName, stName>>
       \/ /\ At("StreamReader", "st_file_lock")
          /\ Acquire("StreamReader", "_lock")
          /\ Goto("StreamReader", "st_file")
          /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
       \/ /\ At("StreamReader", "st_file")
          /\ SectionThenRelease("StreamReader", "_qlock", {"_lock"})
          /\ \/ /\ ActsOn(TRUE) /\ FileHandoverNamed(IF RecordBuiltUnderTheLock THEN shelfName ELSE srName)
                /\ Flags /\ Goto("StreamReader", "done")
             \/ /\ ~ActsOn(TRUE) /\ UNCHANGED <<platVars, wrongTrack, shelfName, dlName>>
                /\ Goto("StreamReader", IF RefusedStreamTriesTheFileFirst THEN "st_stop_lock" ELSE "st_warn")
          /\ UNCHANGED <<jobStatus, shelf, stream, swTr, dlSaw, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>
       \/ /\ At("StreamReader", "st_stop_lock")
          /\ Acquire("StreamReader", "_lock")
          /\ Goto("StreamReader", "st_stop")
          /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
       \/ /\ At("StreamReader", "st_stop")
          /\ SectionThenRelease("StreamReader", "_qlock", {"_lock"})
          /\ LET noFile == jobStatus = "error" \/ (RefusedStreamStopsWithoutTheFile /\ jobStatus = "done" /\ ~shelf)
             IN \/ ActsOn(noFile /\ Waits) /\ StopPlatter /\ Flags /\ Refuses /\ Goto("StreamReader", "done")
                \/ /\ ~ActsOn(noFile /\ Waits) /\ UNCHANGED <<platVars, wrongTrack, refusedPlaying, shelfName, dlName>>
                   /\ Goto("StreamReader", IF ~RefusedStreamTriesTheFileFirst THEN "st_read_shelf"
                                           ELSE IF RefusedStreamTriesTheFileAgain THEN "st_again_read" ELSE "st_warn")
          /\ UNCHANGED <<jobStatus, shelf, stream, swTr, dlSaw, fileWait, stGen, queueVars, localVars, shelfName, dlName>>
       \/ /\ At("StreamReader", "st_read_shelf")
          /\ Goto("StreamReader", IF FileReady THEN "st_file_lock" ELSE "st_warn")
          /\ srName' = IF FileReady THEN shelfName ELSE srName
          /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer, prName, plName, stName>>
       \/ /\ At("StreamReader", "st_again_read")
          /\ Goto("StreamReader", IF FileReady THEN "st_again_lock" ELSE "st_warn")
          /\ srName' = IF FileReady THEN shelfName ELSE srName
          /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resQ, resVer, prName, plName, stName>>
       \/ /\ At("StreamReader", "st_again_lock")
          /\ Acquire("StreamReader", "_lock")
          /\ Goto("StreamReader", "st_again")
          /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
       \/ /\ At("StreamReader", "st_again")
          /\ SectionThenRelease("StreamReader", "_qlock", {"_lock"})
          /\ \/ /\ ActsOn(TRUE) /\ FileHandoverNamed(IF RecordBuiltUnderTheLock THEN shelfName ELSE srName)
                /\ Flags /\ Goto("StreamReader", "done")
             \/ /\ ~ActsOn(TRUE) /\ UNCHANGED <<platVars, wrongTrack, shelfName, dlName>> /\ Goto("StreamReader", "st_warn")
          /\ UNCHANGED <<jobStatus, shelf, stream, swTr, dlSaw, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>
       \/ /\ At("StreamReader", "st_warn")
          /\ Section("StreamReader", "_qlock")
          /\ \/ ActsOn(Waits) /\ Flags /\ Refuses
             \/ ~ActsOn(Waits) /\ UNCHANGED <<wrongTrack, refusedPlaying, shelfName, dlName>>
          /\ Goto("StreamReader", "done")
          /\ UNCHANGED <<platVars, jobStatus, shelf, stream, swTr, dlSaw, fileWait, stGen, queueVars, localVars, shelfName, dlName>>

PlayLocks ==
    /\ WithEngineTry("Play", "pl_try", "pl_swap", "pl_wait")
    /\ plName' = shelfName
    /\ UNCHANGED <<platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead,
                   pwSeen, resQ, resVer, prName, stName, srName>>

PlaySwaps ==
    /\ At("Play", "pl_swap")
    /\ SectionThenRelease("Play", "_qlock", {"fila_lock", "_lock"})
    /\ IF virou.tag /= NoQid
       THEN fila' = Without(fila, virou.tag) /\ virou' = NoSwitch
       ELSE UNCHANGED <<fila, virou>>
    /\ \E r \in IF WithTheRename /\ shelf THEN BOOLEAN ELSE {FALSE} :
          Publish([id |-> nextId, job |-> FALSE, qid |-> NoQid, ver |-> "-", path |-> "file", rec |-> r,
                   name |-> IF r THEN (IF RecordBuiltUnderTheLock THEN shelfName ELSE plName) ELSE 0])
    /\ Goto("Play", "done")
    /\ UNCHANGED <<jobVars, ver, closing, preparando, localVars>>

ForgetsTheRecord ==
    /\ At("Forget", "fg_start")
    /\ shelf' = FALSE
    /\ Goto("Forget", IF WithTheRedownload THEN "fg_back" ELSE "done")
    /\ UNCHANGED <<lockVars, platVars, jobStatus, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

RecordDownloadedAgain ==
    /\ At("Forget", "fg_back")
    /\ \/ stream = "refused" /\ shelf' = TRUE
       \/ UNCHANGED shelf
    /\ Goto("Forget", "done")
    /\ UNCHANGED <<lockVars, platVars, jobStatus, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, queueVars, localVars, shelfName, dlName>>

MixerTime ==
    /\ ~nearEnd
    /\ Playing
    /\ Section("Mixer", "_qlock")
    /\ nearEnd' = TRUE
    /\ UNCHANGED <<pc, track, nextId, line, noReader, gen, pronto, jobVars, queueVars, localVars>>

MixerSwitches ==
    /\ pronto.qid /= NoQid
    /\ Playing
    /\ Section("Mixer", "_qlock")
    /\ virou' = [tag |-> pronto.qid, sai |-> track.id, ver |-> pronto.ver, kept |-> pronto.kept]
    /\ Publish([id |-> nextId, job |-> pronto.job /\ (PassageFileKeepsTheJob \/ pronto.path /= "file"),
                qid |-> pronto.qid, ver |-> pronto.ver, path |-> pronto.path, rec |-> pronto.rec, name |-> pronto.name])
    /\ UNCHANGED <<pc, jobVars, fila, ver, closing, preparando, localVars>>

PrepareReads ==
    /\ At("Prepare", "pr_start")
    /\ Section("Prepare", "fila_lock")
    /\ IF fila /= <<>> /\ Playing /\ pronto.qid = NoQid
       THEN /\ prX' = Head(fila) /\ prLine' = line /\ prTrack' = track.id /\ prGen' = gen
            /\ prVer' = IF PrepareChecksTheVersion THEN ver[Head(fila)] ELSE prVer
            /\ nearEnd' = TRUE
            /\ Goto("Prepare", "pr_mark")
       ELSE UNCHANGED <<prX, prVer, prLine, prTrack, prGen, nearEnd, prName, plName, stName, srName>> /\ Goto("Prepare", "done")
    /\ UNCHANGED <<track, nextId, line, noReader, gen, pronto, jobVars, queueVars, prJob, prPath, stalePrepared,
                   keptHead, pwSeen, resQ, resVer, prName, plName, stName, srName>>

PrepareMarks ==
    /\ At("Prepare", "pr_mark")
    /\ preparando' = prX
    /\ Goto("Prepare", "pr_source")
    /\ UNCHANGED <<lockVars, platVars, jobVars, fila, ver, virou, closing, localVars>>

PrepareSource ==
    /\ At("Prepare", "pr_source")
    /\ DownloadEndsBeforeTheSourcePick => (shelf \/ jobStatus /= "running")
    /\ prVer' = IF PrepareChecksTheVersion THEN prVer ELSE ver[prX]
    /\ \E j \in IF WithTheJobSwitch THEN BOOLEAN ELSE {FALSE}, other \in IF WithTheOtherOnTheShelf THEN BOOLEAN ELSE {FALSE} :
          /\ prJob' = j
          /\ prPath' = CASE ~j -> IF other THEN "file" ELSE "stream"
                         [] shelf /\ PrepareLooksAtTheShelf -> "file"
                         [] jobStatus = "running" \/ ~PrepareLooksAtTheShelf -> "stream"
                         [] OTHER -> "none"
    /\ prName' = shelfName
    /\ Goto("Prepare", "pr_try")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prLine, prTrack, prGen, stalePrepared, keptHead, pwSeen, resQ, resVer, plName, stName, srName>>

PrepareLocks ==
    /\ WithEngineTry("Prepare", "pr_try", "pr_publish", "pr_wait")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

PreparePublishes ==
    /\ At("Prepare", "pr_publish")
    /\ Section("Prepare", "_qlock")
    /\ IF /\ Head0(fila) = prX /\ virou.tag = NoQid /\ line = prLine /\ track.id = prTrack /\ pronto.qid = NoQid
          /\ (PrepareChecksTheVersion => ver[prX] = prVer) /\ prPath /= "none"
       THEN /\ pronto' = [qid |-> prX, ver |-> prVer, job |-> prJob, path |-> prPath, rec |-> prJob, kept |-> FALSE,
                           name |-> IF prPath = "file" /\ prJob /\ RecordBuiltUnderTheLock THEN shelfName
                                    ELSE IF prPath = "file" /\ prJob THEN prName ELSE 0]
            /\ stalePrepared' = (stalePrepared \/ gen /= prGen)
       ELSE UNCHANGED <<pronto, stalePrepared, prName, plName, stName, srName>>
    /\ Goto("Prepare", "pr_release")
    /\ UNCHANGED <<track, nextId, line, noReader, gen, nearEnd, jobVars, queueVars,
                   prX, prVer, prLine, prTrack, prGen, prJob, prPath, keptHead, pwSeen, resQ, resVer, prName, plName, stName, srName>>

PrepareReleases ==
    /\ At("Prepare", "pr_release")
    /\ ReleaseAll("Prepare", {"fila_lock", "_lock"})
    /\ preparando' = NoQid
    /\ Goto("Prepare", "done")
    /\ UNCHANGED <<platVars, jobVars, fila, ver, virou, closing, localVars>>

MoveSwaps ==
    /\ pc["Move"] \in {"mv_swap1", "mv_swap2"}
    /\ SectionBoth("Move", "fila_lock", "_qlock")
    /\ LET f == IF Len(fila) = 2 THEN <<fila[2], fila[1]>> ELSE fila
           h == Head0(Without(f, virou.tag))
       IN /\ fila' = f
          /\ pronto' = IF pronto.qid /= NoQid /\ pronto.qid /= h THEN NoPronto ELSE pronto
    /\ Goto("Move", IF pc["Move"] = "mv_swap1" /\ TwoMoves THEN "mv_swap2" ELSE "done")
    /\ UNCHANGED <<track, nextId, line, noReader, gen, nearEnd, jobVars, ver, virou, closing, preparando, localVars>>

Reserves ==
    \/ /\ At("Reserve", "rs_take")
       /\ SectionBoth("Reserve", "fila_lock", "_qlock")
       /\ IF fila /= <<>> THEN resQ' = Head(fila) /\ resVer' = ver[Head(fila)] ELSE UNCHANGED <<resQ, resVer, prName, plName, stName, srName>>
       /\ Goto("Reserve", IF fila /= <<>> THEN "rs_play" ELSE "done")
       /\ UNCHANGED <<platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, prName, plName, stName, srName>>
    \/ /\ At("Reserve", "rs_play")
       /\ SectionBoth("Reserve", "fila_lock", "_qlock")
       /\ resQ' = NoQid
       /\ Goto("Reserve", "done")
       /\ UNCHANGED <<platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, pwSeen, resVer, prName, plName, stName, srName>>

Seeks ==
    \/ /\ At("Seek", "sk_lock")
       /\ Acquire("Seek", "_lock")
       /\ Goto("Seek", "sk_seek")
       /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>
    \/ /\ At("Seek", "sk_seek")
       /\ SectionThenRelease("Seek", "_qlock", {"_lock"})
       /\ IF track.id /= 0
          THEN /\ gen' = gen + 1
               /\ line' = IF SeekStartsANewLine THEN line + 1 ELSE line
               /\ pronto' = IF SeekStartsANewLine THEN NoPronto ELSE pronto
               /\ nearEnd' = FALSE
               /\ noReader' = FALSE
          ELSE UNCHANGED <<gen, line, pronto, nearEnd, noReader>>
       /\ Goto("Seek", "done")
       /\ UNCHANGED <<track, nextId, jobVars, queueVars, localVars>>

Held1 ==
    IF fila /= <<>> /\ (nearEnd \/ pronto.qid = Head(fila) \/ preparando = Head(fila) \/ resQ = Head(fila))
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
          /\ keptHead' = Held1
          /\ Goto("AudioVersion", "av_swap")
          /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, pwSeen, resQ, resVer, prName, plName, stName, srName>>
       \/ /\ At("AudioVersion", "av_swap")
          /\ \E q \in Qids : ToAudio(q, {keptHead})
          /\ Release("AudioVersion", "fila_lock")
          /\ Goto("AudioVersion", "done")
          /\ UNCHANGED <<platVars, jobVars, fila, virou, closing, preparando, localVars>>

AudioVersionThroughChangeQueue ==
    /\ AudioSwapThroughChangeQueue
    /\ At("AudioVersion", "av_held")
    /\ SectionThenRelease("AudioVersion", "_qlock", {"fila_lock"})
    /\ \E q \in Qids : ToAudio(q, {Held1, virou.tag} \cup (IF AudioVersionKeepsTheReservation THEN {resQ} ELSE {}))
    /\ Goto("AudioVersion", "done")
    /\ UNCHANGED <<platVars, jobVars, fila, virou, closing, preparando, localVars>>

PassageWatcherSees ==
    /\ At("PassageWatcher", "pw_idle")
    /\ virou.tag /= NoQid
    /\ pwSeen' = virou
    /\ Goto("PassageWatcher", "pw_lock")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, prX, prVer, prLine, prTrack, prGen, prJob, prPath, stalePrepared, keptHead, resQ, resVer, prName, plName, stName, srName>>

PassageWatcherLocks ==
    /\ At("PassageWatcher", "pw_lock")
    /\ Acquire("PassageWatcher", "fila_lock")
    /\ Goto("PassageWatcher", "pw_take")
    /\ UNCHANGED <<platVars, jobVars, queueVars, localVars>>

PassageWatcherTakes ==
    \/ /\ At("PassageWatcher", "pw_take")
       /\ virou = pwSeen
       /\ Section("PassageWatcher", "_qlock")
       /\ virou' = NoSwitch
       /\ closing' = pwSeen
       /\ Goto("PassageWatcher", "pw_close")
       /\ UNCHANGED <<platVars, jobVars, fila, ver, preparando, localVars>>
    \/ /\ At("PassageWatcher", "pw_take")
       /\ virou /= pwSeen
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

RenamesOnTheShelf ==
    /\ At("Rename", "rn_shelf")
    /\ shelf
    /\ Section("Rename", "lib_lock")
    /\ shelfName' = 1
    /\ Goto("Rename", "rn_platter")
    /\ UNCHANGED <<platVars, jobStatus, shelf, stream, swTr, dlSaw, wrongTrack, fileWait, stGen, refusedPlaying, dlName,
                   queueVars, localVars>>

RenameSkipped ==
    /\ At("Rename", "rn_shelf")
    /\ Goto("Rename", "done")
    /\ UNCHANGED <<lockVars, platVars, jobVars, queueVars, localVars>>

RenamesOnTheEngine ==
    /\ At("Rename", "rn_platter")
    /\ Section("Rename", "_qlock")
    /\ IF track.rec /\ RenameReplacesTheTrack
       THEN track' = [track EXCEPT !.id = nextId, !.name = shelfName] /\ nextId' = nextId + 1
       ELSE /\ track' = IF track.rec THEN [track EXCEPT !.name = shelfName] ELSE track
            /\ UNCHANGED nextId
    /\ pronto' = IF pronto.rec /\ RenameReachesThePreparedDeck THEN [pronto EXCEPT !.name = shelfName] ELSE pronto
    /\ Goto("Rename", "done")
    /\ UNCHANGED <<line, nearEnd, noReader, gen, jobVars, queueVars, localVars>>

Quiescent ==
    /\ \A p \in Workers : pc[p] = "done"
    /\ At("PassageWatcher", "pw_idle")
    /\ virou.tag = NoQid

Step ==
    \/ DownloadEnds \/ DownloadMarksDone \/ DownloadFailedLock \/ DownloadFailedStop
    \/ DownloadDoneRead \/ DownloadDoneSkip \/ DownloadDoneLock \/ DownloadDoneFile
    \/ SwapChooses \/ SwapFileLocks \/ SwapPublishesTheFile \/ SwapLocks \/ SwapCloses \/ SwapPublishes \/ SwapReleases
    \/ StreamTries \/ StreamOpened \/ StreamReaderStarts \/ StreamReaderEnds \/ StreamReaderReachesItsEnd
    \/ StreamRefusedToday \/ StreamRefusedChecksJob
    \/ PlayLocks \/ PlaySwaps \/ ForgetsTheRecord \/ RecordDownloadedAgain \/ MoveSwaps \/ Reserves \/ Seeks
    \/ MixerTime \/ MixerSwitches
    \/ PrepareReads \/ PrepareMarks \/ PrepareSource \/ PrepareLocks \/ PreparePublishes \/ PrepareReleases
    \/ AudioVersionLocks \/ AudioVersionToday \/ AudioVersionThroughChangeQueue
    \/ PassageWatcherSees \/ PassageWatcherLocks \/ PassageWatcherTakes \/ PassageWatcherCloses
    \/ RenamesOnTheShelf \/ RenameSkipped \/ RenamesOnTheEngine

Next == Step \/ (Quiescent /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ track.id \in Nat /\ track.path \in {"none", "stream", "file"}
    /\ jobStatus \in {"running", "error", "done"}
    /\ stream \in {"pending", "running", "ok", "refused", "gone", "silent", "ended"}
    /\ Range(fila) \subseteq Qids
    /\ ver \in [Qids -> {"video", "audio"}]

Loading == track.job /\ (track.path = "none" \/ fileWait = <<track.id, gen>>) /\ stream \in {"refused", "silent"}

NoOrphanLoading == Quiescent => ~(Loading /\ jobStatus = "error")

NoStaleLoading == Quiescent => ~((Loading \/ noReader) /\ jobStatus = "done")

StreamActsOnItsAttempt == ~wrongTrack

NoRefusalWhilePlaying == ~refusedPlaying

NoPassageFromBeforeTheSeek == ~stalePrepared

FinishedDownloadReachesThePlatter == Quiescent => ~(track.job /\ track.path = "stream" /\ FileReady)

NameIsCurrentOutsideARename == pc["Rename"] /= "rn_platter" => (track.rec => track.name = shelfName)

NoSwitchToAKeptDeck == ~virou.kept

SwapLeavesTheShelfFileOff == ~(pc["Swap"] = "done" /\ track.id = swTr /\ track.id /= 0 /\ ~track.job /\ track.path = "file")

PlatterHasTheCurrentName == Quiescent => (track.rec => track.name = shelfName)

HandoverOnlyOntoTheJobsRecord == (pc["Download"] = "dl_done_file" /\ track.id = dlSaw) => track.path /= "file"

ReservedEntryMatchesRead == resQ /= NoQid /\ resQ \in Range(fila) => ver[resQ] = resVer

SwitchEntryMatchesPlatter ==
    \A sw \in {virou, closing} :
        sw.tag /= NoQid /\ sw.tag \in Range(fila) => ver[sw.tag] = sw.ver

=============================================================================
