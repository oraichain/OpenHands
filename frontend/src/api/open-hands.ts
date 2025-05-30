import { GitRepository, GitUser } from "#/types/git"
import { ApiSettings, PostApiSettings } from "#/types/settings"
import { displayErrorToast } from "#/utils/custom-toast-handlers"
import usePersistStore from "#/zutand-stores/persist-config/usePersistStore"
import { openHands } from "./open-hands-axios"
import {
  AuthenticateResponse,
  Conversation,
  Feedback,
  FeedbackResponse,
  GetConfigResponse,
  GetTrajectoryResponse,
  GetUseCasesItemResponse,
  GetVSCodeUrlResponse,
  GitHubAccessTokenResponse,
  ResultSet,
} from "./open-hands.types"

interface VerifySignatureResponse {
  user: {
    id: string
    publicAddress: string
  }
  token: string
}

interface VerifySignatureRequest {
  signature: string
  message: string
}

class OpenHands {
  /**
   * Retrieve the list of models available
   * @returns List of models available
   */
  static async getModels(): Promise<string[]> {
    const { data } = await openHands.get<string[]>("/api/options/models")
    return data
  }

  /**
   * Retrieve the list of agents available
   * @returns List of agents available
   */
  static async getAgents(): Promise<string[]> {
    const { data } = await openHands.get<string[]>("/api/options/agents")
    const BLACK_LIST = [
      "BrowsingAgent",
      "DummyAgent",
      "VisualBrowsingAgent",
      "FutureTradingAgent",
    ]

    return (data || []).filter((x) => !BLACK_LIST.includes(x))
  }

  /**
   * Retrieve the list of security analyzers available
   * @returns List of security analyzers available
   */
  static async getSecurityAnalyzers(): Promise<string[]> {
    const { data } = await openHands.get<string[]>(
      "/api/options/security-analyzers",
    )
    return data
  }

  static async getConfig(): Promise<GetConfigResponse> {
    const { data } = await openHands.get<GetConfigResponse>(
      "/api/options/config",
    )
    return data
  }

  static async getUseCases(): Promise<GetUseCasesItemResponse> {
    const { data } = await openHands.get<GetUseCasesItemResponse>(
      "/api/options/use-cases",
    )
    return data
  }

  /**
   * Send feedback to the server
   * @param data Feedback data
   * @returns The stored feedback data
   */
  static async submitFeedback(
    conversationId: string,
    feedback: Feedback,
  ): Promise<FeedbackResponse> {
    const url = `/api/conversations/${conversationId}/submit-feedback`
    const { data } = await openHands.post<FeedbackResponse>(url, feedback)
    return data
  }

  /**
   * Authenticate with GitHub token
   * @returns Response with authentication status and user info if successful
   */
  static async authenticate(
    appMode: GetConfigResponse["APP_MODE"],
  ): Promise<boolean> {
    if (appMode === "oss") return true

    const response =
      await openHands.post<AuthenticateResponse>("/api/authenticate")
    return response.status === 200
  }

  /**
   * Get the blob of the workspace zip
   * @returns Blob of the workspace zip
   */
  static async getWorkspaceZip(conversationId: string): Promise<Blob> {
    const url = `/api/conversations/${conversationId}/zip-directory`
    const response = await openHands.get(url, {
      responseType: "blob",
    })
    return response.data
  }

  /**
   * @param code Code provided by GitHub
   * @returns GitHub access token
   */
  static async getGitHubAccessToken(
    code: string,
  ): Promise<GitHubAccessTokenResponse> {
    const { data } = await openHands.post<GitHubAccessTokenResponse>(
      "/api/keycloak/callback",
      {
        code,
      },
    )
    return data
  }

  /**
   * Get the VSCode URL
   * @returns VSCode URL
   */
  static async getVSCodeUrl(
    conversationId: string,
  ): Promise<GetVSCodeUrlResponse> {
    const { data } = await openHands.get<GetVSCodeUrlResponse>(
      `/api/conversations/${conversationId}/vscode-url`,
    )
    return data
  }

  static async getRuntimeId(
    conversationId: string,
  ): Promise<{ runtime_id: string }> {
    const { data } = await openHands.get<{ runtime_id: string }>(
      `/api/conversations/${conversationId}/config`,
    )
    return data
  }

  static async getUserConversations(): Promise<Conversation[]> {
    const { data } = await openHands.get<ResultSet<Conversation>>(
      "/api/conversations?limit=9",
    )
    return data.results
  }

  static async deleteUserConversation(conversationId: string): Promise<void> {
    await openHands.delete(`/api/conversations/${conversationId}`)
  }

  static async updateUserConversation(
    conversationId: string,
    conversation: Partial<Omit<Conversation, "conversation_id">>,
  ): Promise<void> {
    await openHands.patch(`/api/conversations/${conversationId}`, conversation)
  }

  static async createConversation(
    selectedRepository?: GitRepository,
    initialUserMsg?: string,
    imageUrls?: string[],
    replayJson?: string,
  ): Promise<Conversation | undefined> {
    try {
      const body = {
        selected_repository: selectedRepository,
        selected_branch: undefined,
        initial_user_msg: initialUserMsg,
        image_urls: imageUrls,
        replay_json: replayJson,
      }

      const { data } = await openHands.post<Conversation>(
        "/api/conversations",
        body,
      )

      return data
    } catch (error: any) {
      displayErrorToast(
        "response" in error
          ? (error.response?.data?.detail ?? "Error create new conversation")
          : "Error create new conversation",
      )
    }
  }

  static async getConversation(
    conversationId: string,
    isPublic?: boolean | null,
  ): Promise<Conversation | null> {
    const path = isPublic
      ? `/api/options/use-cases/conversations/${conversationId}`
      : `/api/conversations/${conversationId}`
    const { data } = await openHands.get<Conversation | null>(path)

    return data
  }

  /**
   * Get the settings from the server or use the default settings if not found
   */
  static async getSettings(): Promise<ApiSettings> {
    try {
      const { data } = await openHands.get<ApiSettings>("/api/settings")
      return data
    } catch (error) {
      if (error.response.status === 401) {
        const { actions } = usePersistStore.getState()
        actions.reset()
      }
    }
  }

  /**
   * Save the settings to the server. Only valid settings are saved.
   * @param settings - the settings to save
   */
  static async saveSettings(
    settings: Partial<PostApiSettings>,
  ): Promise<boolean> {
    const data = await openHands.post("/api/settings", settings)
    return data.status === 200
  }

  /**
   * Reset user settings in server
   */
  static async resetSettings(): Promise<boolean> {
    const response = await openHands.post("/api/reset-settings")
    return response.status === 200
  }

  static async createCheckoutSession(amount: number): Promise<string> {
    const { data } = await openHands.post(
      "/api/billing/create-checkout-session",
      {
        amount,
      },
    )
    return data.redirect_url
  }

  static async createBillingSessionResponse(): Promise<string> {
    const { data } = await openHands.post(
      "/api/billing/create-customer-setup-session",
    )
    return data.redirect_url
  }

  static async getBalance(): Promise<string> {
    const { data } = await openHands.get<{ credits: string }>(
      "/api/billing/credits",
    )
    return data.credits
  }

  static async getGitUser(): Promise<GitUser> {
    const response = await openHands.get<GitUser>("/api/user/info")

    const { data } = response

    const user: GitUser = {
      id: data.id,
      login: data.login,
      avatar_url: data.avatar_url,
      company: data.company,
      name: data.name,
      email: data.email,
    }

    return user
  }

  static async searchGitRepositories(
    query: string,
    per_page = 5,
  ): Promise<GitRepository[]> {
    const response = await openHands.get<GitRepository[]>(
      "/api/user/search/repositories",
      {
        params: {
          query,
          per_page,
        },
      },
    )

    return response.data
  }

  static async getTrajectory(
    conversationId: string,
  ): Promise<GetTrajectoryResponse> {
    const { data } = await openHands.get<GetTrajectoryResponse>(
      `/api/conversations/${conversationId}/trajectory`,
    )
    return data
  }

  static async logout(appMode: GetConfigResponse["APP_MODE"]): Promise<void> {
    const endpoint =
      appMode === "saas" ? "/api/logout" : "/api/unset-settings-tokens"
    await openHands.post(endpoint)
  }

  /**
   * Verify user's wallet signature and get JWT token
   * @param signature The signature from MetaMask
   * @param publicAddress The public address of the user's wallet
   * @returns The user's public key and JWT token
   */
  static async verifySignature(
    signature: string,
    publicAddress: string,
  ): Promise<VerifySignatureResponse> {
    const { data } = await openHands.post<VerifySignatureResponse>(
      "/api/auth/signup",
      {
        signature,
        publicAddress,
      },
    )
    return data
  }

  /**
   * Get the address for the given network
   * @param network The network to get the address for
   * @returns The address for the given network
   */
  static async getAddressByNetwork(network: string | number): Promise<string> {
    try {
      const { data } = await openHands.get<string>(
        `/api/auth/address-by-network/${network}`,
      )
      return data
    } catch (error) {
      console.error("getAddressByNetwork", error)
      return ""
    }
  }

  /**
   * Change the visibility of a conversation
   * @param conversationId The ID of the conversation
   * @param isPublished Whether the conversation should be publicly visible
   * @returns Whether the request was successful
   */
  static async changeConversationVisibility(
    conversationId: string,
    isPublished: boolean,
  ): Promise<boolean> {
    try {
      const response = await openHands.patch(
        `/api/conversations/${conversationId}/change-visibility`,
        { is_published: isPublished },
      )
      return response.status === 200
    } catch (error) {
      console.error("changeConversationVisibility", error)
      return false
    }
  }

  /**
   * Get the visibility status of a conversation
   * @param conversationId The ID of the conversation
   * @returns Whether the conversation is publicly visible
   */
  static async getConversationVisibility(
    conversationId: string,
  ): Promise<boolean> {
    try {
      const { data } = await openHands.get<boolean>(
        `/api/conversations/${conversationId}/visibility`,
      )
      return data
    } catch (error) {
      console.error("getConversationVisibility", error)
      return false
    }
  }
}

export default OpenHands
