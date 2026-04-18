"""Hand-written GraphQL operations.

Operation names mirror what Monarch's web app uses, so swapping our string for theirs in
network logs makes triage easy. Selection sets are deliberately conservative: we ask only
for what our models bind. When Monarch adds fields we'll add them here, not the other way
around.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Auth-adjacent queries
# ---------------------------------------------------------------------------

ME = """
query Common_GetMe {
  me {
    id
    email
    name
    timezone
  }
}
"""

GET_SUBSCRIPTION = """
query GetSubscriptionDetails {
  subscription {
    id
    status
    paymentSource
    referralCode
    isOnFreeTrial
    hasPremiumEntitlement
  }
}
"""

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

GET_ACCOUNTS = """
query GetAccounts {
  accounts {
    id
    displayName
    type { name display group }
    subtype { name display }
    currentBalance
    displayBalance
    isAsset
    isHidden
    isManual
    includeInNetWorth
    hideFromList
    hideTransactionsFromReports
    syncDisabled
    deactivatedAt
    updatedAt
    createdAt
    mask
    institution {
      id
      name
      url
      logo
      primaryColor
      plaidInstitutionId
      status
    }
  }
  householdPreferences {
    id
    accountGroupOrder
  }
}
"""
# Monarch (Apr 2026) rejects `availableBalance` on Account and `lastRefreshedAt` on
# Institution as part of GetAccounts. Both removed above. The model layer keeps the
# fields as Optional so reintroductions are zero-touch on our side.

GET_ACCOUNT_TYPE_OPTIONS = """
query GetAccountTypeOptions {
  accountTypeOptions {
    type { name display group }
    subtypes { name display }
  }
}
"""

GET_ACCOUNT_HISTORY = """
query AccountDetails_getAccount($id: UUID!, $startDate: Date) {
  account(id: $id) {
    id
    displayName
    historicalBalances(startDate: $startDate) {
      date
      signedBalance
    }
  }
}
"""

GET_RECENT_BALANCES = """
query GetAccountRecentBalances($startDate: Date!) {
  accounts {
    id
    recentBalances(startDate: $startDate)
  }
}
"""

GET_AGGREGATE_SNAPSHOTS = """
query GetAggregateSnapshots($filters: AggregateSnapshotFilters) {
  aggregateSnapshots(filters: $filters) {
    date
    balance
    assetsBalance
    liabilitiesBalance
  }
}
"""

GET_SNAPSHOTS_BY_ACCOUNT_TYPE = """
query GetSnapshotsByAccountType($startDate: Date!, $timeframe: Timeframe!) {
  snapshotsByAccountType(startDate: $startDate, timeframe: $timeframe) {
    accountType
    balance
    date
  }
  accountTypes {
    name
    group
  }
}
"""

# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

GET_TRANSACTIONS = """
query GetTransactionsList(
  $offset: Int,
  $limit: Int,
  $orderBy: TransactionOrdering,
  $filters: TransactionFilterInput
) {
  allTransactions(filters: $filters) {
    totalCount
    results(offset: $offset, limit: $limit, orderBy: $orderBy) {
      id
      date
      amount
      pending
      notes
      plaidName
      originalDescription
      hideFromReports
      needsReview
      isRecurring
      isSplit
      account { id displayName }
      category { id name group { id name type } }
      merchant { id name logoUrl recurringTransactionStream { id } }
      tags { id name color }
      createdAt
      updatedAt
    }
  }
}
"""

GET_TRANSACTION_DETAILS = """
query GetTransactionDrawer($id: UUID!) {
  getTransaction(id: $id) {
    id
    amount
    date
    pending
    notes
    originalDescription
    plaidName
    hideFromReports
    needsReview
    isRecurring
    isSplit
    account { id displayName }
    category { id name group { id name type } }
    merchant { id name logoUrl }
    tags { id name color }
    splitTransactions {
      id
      amount
      notes
      category { id name }
      merchant { name }
    }
  }
}
"""

GET_TRANSACTION_SPLITS = """
query TransactionSplitQuery($id: UUID!) {
  getTransaction(id: $id) {
    id
    amount
    splitTransactions {
      id
      amount
      notes
      category { id name }
      merchant { name }
    }
  }
}
"""

GET_TRANSACTIONS_SUMMARY = """
query GetTransactionsPage($filters: TransactionFilterInput) {
  aggregates(filters: $filters) {
    summary {
      avg
      count
      max
      maxExpense
      sum
      sumIncome
      sumExpense
      first
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Categories, groups, tags
# ---------------------------------------------------------------------------

GET_CATEGORIES = """
query GetCategories {
  categories {
    id
    name
    icon
    color
    order
    isSystemCategory
    isDisabled
    rolloverPeriod
    group {
      id
      name
      type
      isSystemGroup
    }
  }
}
"""

GET_CATEGORY_GROUPS = """
query ManageGetCategoryGroups {
  categoryGroups {
    id
    name
    type
    color
    order
    isSystemGroup
    categories {
      id
      name
      icon
    }
  }
}
"""

GET_TAGS = """
query GetHouseholdTransactionTags {
  householdTransactionTags {
    id
    name
    color
    order
    transactionCount
  }
}
"""

# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

GET_HOLDINGS = """
query Web_GetHoldings($accountIds: [UUID!]) {
  portfolio(accountIds: $accountIds) {
    aggregateHoldings {
      edges {
        node {
          id
          quantity
          basis
          totalValue
          securityPriceChangeDollars
          securityPriceChangePercent
          lastSyncedAt
          holdings {
            id
            account { id displayName }
            quantity
            value
            costBasis
            ticker
            name
            type
            typeDisplay
            closingPrice
            isManual
          }
          # Note (Apr 2026, probed live): Monarch rejects `basis` and `lastPricedAt`
          # on the nested Holding type here. `basis` is still valid at the parent
          # aggregateHoldings.node level above, so we keep that one.
          security {
            id
            name
            ticker
            type
            typeDisplay
            currentPrice
            currentPriceUpdatedAt
            closingPrice
            closingPriceUpdatedAt
          }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Cashflow & budgets
# ---------------------------------------------------------------------------

GET_CASHFLOW = """
query Web_GetCashFlowPage($filters: TransactionFilterInput) {
  byCategory: aggregates(filters: $filters, groupBy: ["category"]) {
    groupBy { category { id name group { id name type } } }
    summary { sum sumIncome sumExpense count }
  }
  byCategoryGroup: aggregates(filters: $filters, groupBy: ["categoryGroup"]) {
    groupBy { categoryGroup { id name type } }
    summary { sum sumIncome sumExpense count }
  }
  byMerchant: aggregates(filters: $filters, groupBy: ["merchant"]) {
    groupBy { merchant { id name } }
    summary { sum sumIncome sumExpense count }
  }
  summary: aggregates(filters: $filters, fillEmptyValues: true) {
    summary {
      sumIncome
      sumExpense
      savings
      savingsRate
    }
  }
}
"""

GET_BUDGETS = """
query Common_GetJointPlanningData(
  $startDate: Date!,
  $endDate: Date!,
  $useLegacyGoals: Boolean
) {
  budgetSystem
  budgetData(startMonth: $startDate, endMonth: $endDate) {
    monthlyAmountsByCategory {
      category { id name group { id name type } }
      monthlyAmounts {
        month
        plannedCashFlowAmount
        plannedSetAsideAmount
        actualAmount
        remainingAmount
        previousMonthRolloverAmount
        rolloverType
      }
    }
    monthlyAmountsByCategoryGroup {
      categoryGroup { id name type }
      monthlyAmounts {
        month
        plannedCashFlowAmount
        actualAmount
        remainingAmount
      }
    }
    totalsByMonth {
      month
      totalIncome { plannedAmount actualAmount }
      totalExpenses { plannedAmount actualAmount }
      totalFixedExpenses { plannedAmount actualAmount }
      totalNonMonthlyExpenses { plannedAmount actualAmount }
      totalFlexibleExpenses { plannedAmount actualAmount }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Recurring & goals
# ---------------------------------------------------------------------------

GET_RECURRING = """
query Web_GetUpcomingRecurringTransactionItems(
  $startDate: Date!,
  $endDate: Date!,
  $filters: RecurringTransactionFilter
) {
  recurringTransactionItems(
    startDate: $startDate,
    endDate: $endDate,
    filters: $filters
  ) {
    stream {
      id
      frequency
      amount
      isApproximate
      name
      logoUrl
      merchant { id name }
      creditReportLiabilityAccount { id account { id displayName } }
    }
    date
    isPast
    transactionId
    amount
    amountDiff
    category { id name }
    account { id displayName }
  }
}
"""

GET_GOALS = """
query Web_GetGoals {
  goalsV2 {
    id
    name
    imageStorageProvider
    imageStorageProviderId
    objective
    targetDate
    targetAmount
    currentAmount
    monthlyContribution
    isCompleted
    completedAt
    accountAllocations {
      account { id displayName }
      currentAmount
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Institutions
# ---------------------------------------------------------------------------

GET_INSTITUTIONS = """
query Web_GetInstitutionSettings {
  credentials {
    id
    institution {
      id
      name
      url
      logo
      primaryColor
      status
      plaidInstitutionId
    }
    dataProvider
    updateRequired
    disconnectedFromDataProviderAt
    syncDisabledAt
    syncDisabledReason
    accounts {
      id
      displayName
      currentBalance
    }
  }
}
"""
