import { ScrollToBottomButton } from "#/components/shared/buttons/scroll-to-bottom-button"
import Security from "#/components/shared/modals/security/security"
import {
  useWsClient,
  WsClientProviderStatus,
  ReplayStatus,
} from "#/context/ws-client-provider"
import { useGetTrajectory } from "#/hooks/mutation/use-get-trajectory"
import { useListFiles } from "#/hooks/query/use-list-files"
import { useSettings } from "#/hooks/query/use-settings"
import { useScrollToBottom } from "#/hooks/use-scroll-to-bottom"
import { I18nKey } from "#/i18n/declaration"
import { generateAgentStateChangeEvent } from "#/services/agent-state-service"
import { createChatMessage } from "#/services/chat-service"
import { addUserMessage } from "#/state/chat-slice"
import { setCurrentPathViewed } from "#/state/file-state-slice"
import { RootState } from "#/store"
import { AgentState } from "#/types/agent-state"
import { convertImageToBase64 } from "#/utils/convert-image-to-base-64"
import {
  displayErrorToast,
  displaySuccessToast,
} from "#/utils/custom-toast-handlers"
import { downloadTrajectory } from "#/utils/download-trajectory"
import { useDisclosure } from "@heroui/react"
import posthog from "posthog-js"
import React, { useEffect } from "react"
import { useTranslation } from "react-i18next"
import { FaPowerOff, FaCheck } from "react-icons/fa6"
import { FaFileInvoice, FaLink } from "react-icons/fa"
import { IoFolder } from "react-icons/io5"
import { RiPhoneFindLine } from "react-icons/ri"
import { useDispatch, useSelector } from "react-redux"
import { twMerge } from "tailwind-merge"
import { useLocation, useParams } from "react-router"
import { Controls } from "../controls/controls"
import { FeedbackModal } from "../feedback/feedback-modal"
import FileExplorerModal from "../file-explorer/modal-file-explorer"
import { TrajectoryActions } from "../trajectory/trajectory-actions"
import { ActionSuggestions } from "./action-suggestions"
import { InteractiveChatBox } from "./interactive-chat-box"
import { Messages } from "./messages"
import { SkeletonMessage } from "./skeleton-message"
import { TypingIndicator } from "./typing-indicator"

function getEntryPoint(
  hasRepository: boolean | null,
  hasReplayJson: boolean | null,
): string {
  if (hasRepository) return "github"
  if (hasReplayJson) return "replay"
  return "direct"
}

interface DisconnectButtonProps {
  handleDisconnect: () => void
  isDisabled: boolean
}

export function DisconnectButton({
  handleDisconnect,
  isDisabled,
}: DisconnectButtonProps) {
  if (isDisabled) {
    return null
  }

  return (
    <button
      title="Disconnect"
      onClick={handleDisconnect}
      type="button"
      disabled={isDisabled}
      className={`rounded-lg px-3 py-2 font-medium transition-colors ${
        isDisabled
          ? "cursor-not-allowed bg-red-200"
          : "bg-red-100 text-red-500 hover:bg-red-50"
      }`}
    >
      <FaPowerOff />
      {/* {t(isDisabled ? "Connect" : "Disconnect")} */}
    </button>
  )
}

export function ChatInterface() {
  const { data: settings } = useSettings()
  const {
    isOpen: securityModalIsOpen,
    onOpen: onSecurityModalOpen,
    onOpenChange: onSecurityModalOpenChange,
  } = useDisclosure()
  const dispatch = useDispatch()
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const {
    send,
    isLoadingMessages,
    disconnect,
    status,
    skipToResults,
    replayStatus,
    resetReplay,
  } = useWsClient()
  const { t } = useTranslation()
  const { scrollDomToBottom, onChatBodyScroll, hitBottom } =
    useScrollToBottom(scrollRef)

  const location = useLocation()

  const isShareRoute = React.useMemo(() => {
    return location.pathname.startsWith("/share/")
  }, [location.pathname])

  const { messages } = useSelector((state: RootState) => state.chat)
  const { curAgentState } = useSelector((state: RootState) => state.agent)
  const {
    data: files,
    refetch: refetchFiles,
    error,
  } = useListFiles({
    isCached: false,
    enabled: true,
  })

  useEffect(() => {
    if (files?.length) {
      const htmlFiles = []
      const txtFiles = []
      const mdFiles = []

      files.map((e) => {
        if (e.includes(".html")) {
          htmlFiles.push(e)
        } else if (e.includes(".md")) {
          mdFiles.push(e)
        } else if (e.includes(".txt")) {
          txtFiles.push(e)
        }
      })
      const priorityFile = mdFiles[0] || txtFiles[0] || htmlFiles[0]
      if (priorityFile) {
        dispatch(setCurrentPathViewed(priorityFile))
      }
    }
  }, [files])

  useEffect(() => {
    if (curAgentState === AgentState.AWAITING_USER_INPUT) refetchFiles()
  }, [curAgentState])

  useEffect(() => {
    if (files && files.length > 0) {
      scrollDomToBottom()
    }
  }, [files])
  useEffect(() => {
    if (messages && messages.length > 0) {
      scrollDomToBottom()
    }
  }, [messages])

  const [feedbackPolarity, setFeedbackPolarity] = React.useState<
    "positive" | "negative"
  >("positive")
  const [feedbackModalIsOpen, setFeedbackModalIsOpen] = React.useState(false)
  const [explorerModal, setExplorerModal] = React.useState(false)
  const [selectedPath, setSelectedPath] = React.useState(null)

  const { currentPathViewed } = useSelector(
    (state: RootState) => state.fileState,
  )

  const [messageToSend, setMessageToSend] = React.useState<string | null>(null)
  const { selectedRepository, replayJson } = useSelector(
    (state: RootState) => state.initialQuery,
  )
  const params = useParams()
  const { mutate: getTrajectory } = useGetTrajectory()

  const handleSendMessage = async (content: string, msgFiles: File[]) => {
    if (messages.length === 0) {
      posthog.capture("initial_query_submitted", {
        entry_point: getEntryPoint(
          selectedRepository !== null,
          replayJson !== null,
        ),
        query_character_length: content.length,
        replay_json_size: replayJson?.length,
      })
    } else {
      posthog.capture("user_message_sent", {
        session_message_count: messages.length,
        current_message_length: content.length,
      })
    }
    const promises = msgFiles.map((file) => convertImageToBase64(file))
    const imageUrls = await Promise.all(promises)

    const timestamp = new Date().toISOString()
    const pending = true
    dispatch(addUserMessage({ content, imageUrls, timestamp, pending }))
    send(createChatMessage(content, imageUrls, timestamp))
    setMessageToSend(null)
  }

  const handleStop = () => {
    posthog.capture("stop_button_clicked")
    send(generateAgentStateChangeEvent(AgentState.STOPPED))
  }

  const handleDisconnect = () => {
    posthog.capture("websocket_disconnect_clicked")
    disconnect()
  }

  const handleSkipToResults = () => {
    posthog.capture("skip_to_results_clicked")
    skipToResults()
  }

  const handleWatchAgain = () => {
    posthog.capture("watch_again_clicked")
    resetReplay()
  }

  const onClickShareFeedbackActionButton = async (
    polarity: "positive" | "negative",
  ) => {
    setFeedbackModalIsOpen(true)
    setFeedbackPolarity(polarity)
  }

  const onClickExportTrajectoryButton = () => {
    if (!params.conversationId) {
      displayErrorToast(t(I18nKey.CONVERSATION$DOWNLOAD_ERROR))
      return
    }

    getTrajectory(params.conversationId, {
      onSuccess: async (data) => {
        await downloadTrajectory(
          params.conversationId ?? t(I18nKey.CONVERSATION$UNKNOWN),
          data.trajectory,
        )
      },
      onError: () => {
        displayErrorToast(t(I18nKey.CONVERSATION$DOWNLOAD_ERROR))
      },
    })
  }

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      displaySuccessToast("Share URL copied to clipboard!")
    } catch (error) {
      displayErrorToast(t(I18nKey.CHAT_INTERFACE$CHAT_MESSAGE_COPY_FAILED))
    }
  }

  const isWaitingForUserInput =
    curAgentState === AgentState.AWAITING_USER_INPUT ||
    curAgentState === AgentState.FINISHED

  return (
    <div className="mx-auto flex h-full max-w-[800px] flex-col justify-between">
      <div
        ref={scrollRef}
        onScroll={(e) => onChatBodyScroll(e.currentTarget)}
        className="fast-smooth-scroll flex grow flex-col gap-2 overflow-y-auto overflow-x-hidden px-4 pt-4"
      >
        {isLoadingMessages ||
          (messages.length === 0 && (
            <div className="space-y-6">
              <SkeletonMessage type="user" />
              <SkeletonMessage type="assistant" />
              <SkeletonMessage type="user" />
            </div>
          ))}

        {!isLoadingMessages && (
          <Messages
            messages={messages}
            isAwaitingUserConfirmation={
              curAgentState === AgentState.AWAITING_USER_CONFIRMATION
            }
          />
        )}

        {isWaitingForUserInput && (
          <ActionSuggestions
            onSuggestionsClick={(value) => handleSendMessage(value, [])}
          />
        )}

        {isWaitingForUserInput &&
          (!isShareRoute || replayStatus === ReplayStatus.COMPLETED) && (
            <div className="-mt-3 mb-4 flex w-fit items-center justify-center gap-2 rounded-full bg-success-100 px-3 py-1 text-[14px]">
              <FaCheck />
              Thesis has completed the current task
            </div>
          )}

        {isWaitingForUserInput &&
          files &&
          files.length > 0 &&
          (!isShareRoute || replayStatus === ReplayStatus.COMPLETED) && (
            <div className="my-3 flex flex-wrap gap-2 border-t border-neutral-900 pt-3">
              {files.slice(0, 2).map((file) => {
                const isDirectory = file.endsWith("/")
                return (
                  <div
                    key={file}
                    className={twMerge(
                      "flex w-fit max-w-full cursor-pointer items-center gap-2 rounded-md bg-neutral-1000 p-2 hover:opacity-70",
                      currentPathViewed.includes(file) &&
                        "border border-blue-200 bg-blue-50",
                    )}
                    onClick={() => {
                      if (isDirectory) {
                        setExplorerModal(true)
                        setSelectedPath(file)
                      } else {
                        dispatch(setCurrentPathViewed(file))
                      }
                    }}
                  >
                    {isDirectory ? (
                      <IoFolder className="h-4 w-4 shrink-0 fill-blue-500" />
                    ) : (
                      <FaFileInvoice className="h-4 w-4 shrink-0 fill-blue-500" />
                    )}
                    <div className="line-clamp-1 text-sm">{file}</div>
                  </div>
                )
              })}
              {files.length >= 2 && (
                <div
                  className="flex w-fit max-w-full cursor-pointer items-center gap-2 rounded-md bg-neutral-1000 p-2 hover:opacity-70"
                  onClick={() => {
                    setExplorerModal(true)
                    setSelectedPath(null)
                  }}
                >
                  <RiPhoneFindLine className="h-4 w-4 shrink-0 fill-blue-500" />
                  <div className="line-clamp-1 text-sm">
                    View all files in this task
                  </div>
                </div>
              )}
            </div>
          )}

        {/* {!error && <ExplorerTree files={files || []} />} */}
      </div>
      {isShareRoute ? (
        <div className="flex items-center justify-between bg-[rgba(0,0,0,0.05)] px-4 py-2">
          <p className="text-sm">
            {replayStatus === ReplayStatus.COMPLETED
              ? "Task replay completed"
              : "Thesis is replaying the task..."}
          </p>
          <div className="flex items-center gap-2">
            <button
              className="flex items-center gap-1 rounded-md px-2 py-2 text-sm text-[rgba(0,0,0,0.8)] hover:text-[rgba(0,0,0,0.8)]"
              onClick={handleCopyLink}
              title={t("Copy share link")}
            >
              <FaLink size={16} />
            </button>
            {replayStatus === ReplayStatus.COMPLETED ? (
              <button
                className="rounded-md bg-[rgba(0,0,0,0.8)] px-4 py-2 text-sm text-white hover:bg-[rgba(0,0,0,0.7)]"
                onClick={handleWatchAgain}
              >
                Watch again
              </button>
            ) : (
              <button
                className="rounded-md bg-[rgba(0,0,0,0.8)] px-4 py-2 text-sm text-white hover:bg-[rgba(0,0,0,0.7)]"
                onClick={handleSkipToResults}
              >
                Skip to results
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-[6px] px-4 pb-4">
          <div className="relative flex justify-between">
            <TrajectoryActions
              onPositiveFeedback={() =>
                onClickShareFeedbackActionButton("positive")
              }
              onNegativeFeedback={() =>
                onClickShareFeedbackActionButton("negative")
              }
              onExportTrajectory={() => onClickExportTrajectoryButton()}
            />

            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 transform">
              {curAgentState === AgentState.RUNNING && <TypingIndicator />}
            </div>

            {!hitBottom && <ScrollToBottomButton onClick={scrollDomToBottom} />}
          </div>

          <div className="flex items-center gap-2">
            <InteractiveChatBox
              onSubmit={handleSendMessage}
              onStop={handleStop}
              isDisabled={
                curAgentState === AgentState.LOADING ||
                curAgentState === AgentState.AWAITING_USER_CONFIRMATION ||
                status === WsClientProviderStatus.DISCONNECTED
              }
              mode={curAgentState === AgentState.RUNNING ? "stop" : "submit"}
              value={messageToSend ?? undefined}
              onChange={setMessageToSend}
              className="w-full flex-grow" // Ensure chat box takes full width minus space for the button
            />
          </div>
          <div className="flex w-full items-center justify-between gap-2">
            {settings && (
              <Security
                isOpen={securityModalIsOpen}
                onOpenChange={onSecurityModalOpenChange}
                securityAnalyzer={settings.SECURITY_ANALYZER}
              />
            )}
            <Controls
              setSecurityOpen={onSecurityModalOpen}
              showSecurityLock={!!settings?.SECURITY_ANALYZER}
            />
            <DisconnectButton
              handleDisconnect={handleDisconnect}
              isDisabled={
                !isWaitingForUserInput &&
                status !== WsClientProviderStatus.DISCONNECTED
              }
            />
          </div>
        </div>
      )}

      <FeedbackModal
        isOpen={feedbackModalIsOpen}
        onClose={() => setFeedbackModalIsOpen(false)}
        polarity={feedbackPolarity}
      />
      <FileExplorerModal
        filePath={selectedPath}
        isOpen={explorerModal}
        onClose={() => setExplorerModal(false)}
      />
    </div>
  )
}
