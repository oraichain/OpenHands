import { AgentSettingsDropdownInput } from "#/components/features/settings/agent-setting-dropdown-input"
import { BrandButton } from "#/components/features/settings/brand-button"
import { HeroHeading } from "#/components/shared/hero-heading"
import { SampleMsg } from "#/components/shared/sample-msg"
import { TaskForm } from "#/components/shared/task-form"
import { InvitationCodeComponent } from "#/components/shared/invitation-code/invitation-code-component"
import { useAIConfigOptions } from "#/hooks/query/use-ai-config-options"
import { useSettings } from "#/hooks/query/use-settings"
import { I18nKey } from "#/i18n/declaration"
import { useGetJwt } from "#/zutand-stores/persist-config/selector"
import { useConnectModal } from "@rainbow-me/rainbowkit"
import React from "react"
import { useTranslation } from "react-i18next"
import { useAccount } from "wagmi"
import { useInvitationCode } from "#/hooks/use-invitation-code"
import { LoadingSpinner } from "#/components/shared/loading-spinner"

function Home() {
  const { t } = useTranslation()
  const { data: settings } = useSettings()
  const { isConnected } = useAccount()
  const jwt = useGetJwt()
  const formRef = React.useRef<HTMLFormElement>(null)
  const { data: resources } = useAIConfigOptions()

  const { openConnectModal } = useConnectModal()
  const {
    needsInvitation,
    refreshStatus,
    isLoading: isLoadingInvitationStatus,
  } = useInvitationCode()

  const isUserLoggedIn = !!jwt && !!isConnected

  const handleInvitationSuccess = () => {
    refreshStatus()
  }

  if (isLoadingInvitationStatus) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <LoadingSpinner size="large" />
      </div>
    )
  }

  // If user is logged in and needs invitation, show only the invitation component
  if (isUserLoggedIn && needsInvitation) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <InvitationCodeComponent onSuccess={handleInvitationSuccess} />
      </div>
    )
  }

  // Otherwise show the regular home page
  return (
    <div
      data-testid="home-screen"
      className="relative flex h-full flex-col items-center justify-center overflow-y-auto bg-neutral-1100 px-2 dark:bg-neutral-200"
    >
      <HeroHeading />
      <div className="mt-8 flex w-full flex-col items-center gap-1 md:w-[600px]">
        <div className="flex w-full flex-col gap-2">
          {isUserLoggedIn ? (
            <TaskForm ref={formRef} />
          ) : (
            <div className="flex w-full flex-col gap-2">
              <div className="text-center text-neutral-700 dark:text-tertiary-light">
                Welcome to Thesis! We&rsquo;re currently in private beta.
                <br /> To get started, Please enter connect your wallet.
              </div>

              <BrandButton
                testId="connect-your-wallet"
                type="button"
                variant="secondary"
                className="mt-2 w-full rounded-xl border-content bg-primary font-bold uppercase text-white hover:brightness-110"
                onClick={openConnectModal}
              >
                {t(I18nKey.BUTTON$CONNECT_WALLET)}
              </BrandButton>
            </div>
          )}
        </div>

        {(!isUserLoggedIn || (isUserLoggedIn && !needsInvitation)) && (
          <>
            <div className="w-full">
              {settings && (
                <AgentSettingsDropdownInput
                  testId="agent-input-show"
                  name="agent-input"
                  label="Agent"
                  items={
                    resources?.agents.map((agent) => ({
                      key: agent,
                      label: agent,
                    })) || []
                  }
                  defaultSelectedKey={settings?.AGENT}
                  isClearable={false}
                  showOptionalTag={false}
                  className="flex-row"
                />
              )}
            </div>
            <div className="mt-8 w-full text-left text-[16px] font-semibold text-neutral-700 dark:text-tertiary-light">
              Try our use case
            </div>
            <SampleMsg />
          </>
        )}
        {/* <UseCaseList /> */}
        {/* <div className="flex gap-4 w-full flex-col md:flex-row mt-8">
          <GitHubRepositoriesSuggestionBox
            handleSubmit={() => formRef.current?.requestSubmit()}
            gitHubAuthUrl={gitHubAuthUrl}
            user={user || null}
          />
          {ENABLE_TRAJECTORY_REPLAY() && (
            <ReplaySuggestionBox
              onChange={async (event) => {
                if (event.target.files) {
                  const json = event.target.files[0];
                  dispatch(setReplayJson(await convertFileToText(json)));
                  posthog.capture("json_file_uploaded");
                  formRef.current?.requestSubmit();
                } else {
                  // TODO: handle error
                }
              }}
            />
          )}
        </div>
        <div className="w-full flex justify-start mt-2 ml-2">
          <CodeNotInGitHubLink />
        </div> */}
      </div>
    </div>
  )
}

export default Home
