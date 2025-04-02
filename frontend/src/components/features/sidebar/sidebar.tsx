import React from "react";
import { useDispatch } from "react-redux";
import posthog from "posthog-js";
import { NavLink, useLocation } from "react-router";
import { useGitHubUser } from "#/hooks/query/use-github-user";
import { UserActions } from "./user-actions";
import { AllHandsLogoButton } from "#/components/shared/buttons/all-hands-logo-button";
import { DocsButton } from "#/components/shared/buttons/docs-button";
import { ExitProjectButton } from "#/components/shared/buttons/exit-project-button";
import { SettingsButton } from "#/components/shared/buttons/settings-button";
import { SettingsModal } from "#/components/shared/modals/settings/settings-modal";
import { useSettings } from "#/hooks/query/use-settings";
import { ConversationPanel } from "../conversation-panel/conversation-panel";
import { useEndSession } from "#/hooks/use-end-session";
import { setCurrentAgentState } from "#/state/agent-slice";
import { AgentState } from "#/types/agent-state";
import { TooltipButton } from "#/components/shared/buttons/tooltip-button";
import { ConversationPanelWrapper } from "../conversation-panel/conversation-panel-wrapper";
import { useLogout } from "#/hooks/mutation/use-logout";
import { useConfig } from "#/hooks/query/use-config";
import { cn } from "#/utils/utils";
import { displayErrorToast } from "#/utils/custom-toast-handlers";
import ChatIcon from "#/icons/chat-icon.svg?react";
export function Sidebar() {
  const location = useLocation();
  const dispatch = useDispatch();
  const endSession = useEndSession();
  const user = useGitHubUser();
  const { data: config } = useConfig();
  const {
    data: settings,
    error: settingsError,
    isError: settingsIsError,
    isFetching: isFetchingSettings,
  } = useSettings();
  const { mutateAsync: logout } = useLogout();

  const [settingsModalIsOpen, setSettingsModalIsOpen] = React.useState(false);

  const [conversationPanelIsOpen, setConversationPanelIsOpen] =
    React.useState(false);

  // TODO: Remove HIDE_LLM_SETTINGS check once released
  const shouldHideLlmSettings =
    config?.FEATURE_FLAGS.HIDE_LLM_SETTINGS && config?.APP_MODE === "saas";

  React.useEffect(() => {
    if (shouldHideLlmSettings) return;

    if (location.pathname === "/settings") {
      setSettingsModalIsOpen(false);
    } else if (
      !isFetchingSettings &&
      settingsIsError &&
      settingsError?.status !== 404
    ) {
      // We don't show toast errors for settings in the global error handler
      // because we have a special case for 404 errors
      displayErrorToast(
        "Something went wrong while fetching settings. Please reload the page.",
      );
    } else if (config?.APP_MODE === "oss" && settingsError?.status === 404) {
      setSettingsModalIsOpen(true);
    }
  }, [
    settingsError?.status,
    settingsError,
    isFetchingSettings,
    location.pathname,
  ]);

  const handleEndSession = () => {
    dispatch(setCurrentAgentState(AgentState.LOADING));
    endSession();
  };

  const handleLogout = async () => {
    await logout();
    posthog.reset();
  };

  console.log({ settingsModalIsOpen });
  return (
    <>
      <aside className="h-[50px] bg-[#141415] md:h-auto px-3 py-3 flex flex-row md:flex-col gap-1">
        <nav className="flex flex-row md:flex-col items-center justify-between w-full h-auto md:w-auto md:h-full">
          <div className="flex flex-row md:flex-col items-center gap-[26px] max-md:gap-4">
            <div className="flex items-center justify-center">
              <AllHandsLogoButton onClick={handleEndSession} />
            </div>
            <ExitProjectButton
              onClick={handleEndSession}
              isActive={location.pathname === "/" && !conversationPanelIsOpen}
            />
            <TooltipButton
              testId="toggle-conversation-panel"
              tooltip="Conversations"
              className={cn(
                "w-10 h-10 rounded-lg p-2 flex items-center justify-center",
                conversationPanelIsOpen && "bg-[#262525]",
              )}
              ariaLabel="Conversations"
              onClick={() => setConversationPanelIsOpen((prev) => !prev)}
            >
              <ChatIcon
                className={cn(
                  "opacity-50 transition-colors",
                  conversationPanelIsOpen && "opacity-100",
                )}
              />
            </TooltipButton>
          </div>

          <div className="flex flex-row md:flex-col items-center gap-[26px] max-md:gap-3 md:mb-4">
            <DocsButton />
            <UserActions
              user={
                user.data ? { avatar_url: user.data.avatar_url } : undefined
              }
              onLogout={handleLogout}
              isLoading={user.isFetching}
            />
            <NavLink to="/settings">
              <SettingsButton />
            </NavLink>
          </div>
        </nav>

        {conversationPanelIsOpen && (
          <ConversationPanelWrapper isOpen={conversationPanelIsOpen}>
            <ConversationPanel
              onClose={() => setConversationPanelIsOpen(false)}
            />
          </ConversationPanelWrapper>
        )}
      </aside>

      {settingsModalIsOpen && (
        <SettingsModal
          settings={settings}
          onClose={() => setSettingsModalIsOpen(false)}
        />
      )}
    </>
  );
}
