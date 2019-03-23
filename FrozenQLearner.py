import numpy as np
import logging
import io

from gym.envs.registration import register
from gym import make
register(
    id='FrozenLakeNotSlippery-v0',
    entry_point='gym.envs.toy_text:FrozenLakeEnv',
    kwargs={'map_name' : '4x4', 'is_slippery': False}
)


class FrozenLearner:

    def __init__(self, episodes, alpha, gamma):

        # Initialise FL environment
        self.FLenv = make('FrozenLakeNotSlippery-v0')
        self.map = map = self.FLenv.desc

        # Check the map row sizes are consistent
        row_lens = [len(row) for row in map]
        assert (min(row_lens) == max(row_lens) & len(map) == row_lens[0]), "Inconsistent row sizes"

        # Get the number of states
        self.mapLen = len(map)
        self.numS = numS = len(map) * len(map[0])
        self.numA = numA = 4

        # Initialise empty R and Q matrices
        self.R = np.empty((numS, numA)) * np.nan
        self.Q = np.empty((numS, numA)) * np.nan

        # Initialise parameters
        self.alpha = alpha
        self.gamma = gamma
        self.episodes = episodes


    def get_state(self, map_row, map_col):
        return map_row * self.mapLen + map_col

    def from_state(self, state):
        return (state // self.mapLen, state % self.mapLen)

    def evaluate_action(self, map_row, map_col, a):
        if a == 0:  # left
            map_col = max(map_col - 1, 0)
        elif a == 1:  # down
            map_row = min(map_row + 1, self.mapLen - 1)
        elif a == 2:  # right
            map_col = min(map_col + 1, self.mapLen - 1)
        elif a == 3:  # up
            map_row = max(map_row - 1, 0)
        return (map_row, map_col)

    def is_wall_move(self, row, col, a):
        return self.evaluate_action(row, col, a) == (row, col)

    def init_R(self, val_goal, val_other, wall_moves):
        if wall_moves:
            self.R.fill(0)
        for rowS in range(self.numS):
            for colA in range(self.numA):
                map_row, map_col = self.from_state(rowS)
                if not wall_moves:
                    if self.is_wall_move(map_row, map_col, colA):
                        self.R[rowS, colA] = np.nan
                    elif self.map[self.evaluate_action(map_row, map_col, colA)] == b'G':
                        self.R[rowS, colA] = val_goal
                    else:
                        self.R[rowS, colA] = val_other

    def init_Q(self):
        assert (self.R is not None), "Missing R matrix"
        self.Q = np.array([[0 if not np.isnan(el) else np.nan for el in row] for row in self.R])

    def normalise_Q(self, norm_type):
        if norm_type == 'sum':
            if np.nansum(self.Q) > 0:
                self.Q = self.Q / np.nansum(self.Q)
        elif norm_type == 'max':
            if np.nanmax(self.Q) > 0:
                self.Q = self.Q / np.nanmax(self.Q)

    def rdm_opt_act(self,state):
        poss_Q = self.Q[state, :]
        max_inds = [i for i, o_a in enumerate(poss_Q) if o_a == np.nanmax(poss_Q)]
        logging.debug('Indices of optimal actions %s',max_inds)
        if len(max_inds) > 1:
            action = max_inds[np.random.randint(len(max_inds))]
        else:
            action = np.nanargmax(poss_Q)
        return action

    def rdm_poss_act(self, state):
        poss_Q = self.Q[state, :]
        logging.debug('Selecting from Q values %s', poss_Q)
        action = np.random.randint(self.numA)
        while np.isnan(poss_Q[action]):
            action = np.random.randint(self.numA)
        return action

    # Write the results of each episode to file
    @staticmethod
    def open_file(in_memory,file_desc,header):
        if not in_memory:
            outfile = open('outputs/%s.csv' % file_desc.replace(' ', '_'), 'w')
        else:
            outfile = io.StringIO()
        outfile.write('%s\n' % header)
        return outfile


class FrozenQLearner(FrozenLearner):

    def __init__(self, episodes, alpha, gamma, epsilon_start, df1, df2):
        super(FrozenQLearner,self).__init__(episodes,alpha,gamma)
        self.epsilon = epsilon_start
        self.df1 = df1
        self.df2 = df2

    def update_Q(self, state_1, action, reward, state_2):
        learned_value = self.R[state_1, action] + self.gamma * self.Q[state_2, np.nanargmax(self.Q[state_2, :])]
        self.Q[state_1, action] = (1 - self.alpha) * self.Q[state_1, action] + self.alpha * (learned_value)

    def update_epsilon(self, random_value):
        if random_value > self.epsilon:
            self.epsilon *= self.df1
        else:
            self.epsilon *= self.df2

    def select_action(self, state, random_value):
        is_random = random_value < self.epsilon
        if is_random:
            logging.debug('Selecting random action')
            action = self.rdm_poss_act(state)
        else:
            action = self.rdm_opt_act(state)
        return action, is_random

    def execute(self, log_level, write_file, file_desc, norm_method='max', in_memory=False):

        logging.basicConfig(level=log_level)

        episode = 0
        state = self.FLenv.reset()
        self.init_R(val_goal=100, val_other=0, wall_moves=False)
        logging.info('%s\nRunning Q-learning Experiment\n alpha=%3.2f,gamma=%3.2f,epsilon_start=%3.2f,''df1=%3.2f,'
                     'df2=%3.2f \n%s','*' * 30, self.alpha, self.gamma,self.epsilon,self.df1,self.df2, '*' * 30)
        logging.debug('Reward matrix %s', self.R)
        self.init_Q()

        def episode_metrics():
            return '%d,%d,%4.2f,%s,%d,%4.2f' % (
            episode, ep_steps, ep_total_reward, ep_outcome, ep_steps_random, ep_epsilon_start)

        def metric_headers():
            return 'Episode,Steps,Total_Reward,Outcome,Steps_random,Epsilon_start'

        if write_file:
            outfile = self.open_file(in_memory,file_desc,metric_headers())

        # Start Q-learning
        while episode < self.episodes:
            episode_complete = False
            step = 0
            ep_total_reward = 0
            ep_epsilon_start = self.epsilon
            ep_steps_random = 0

            while not episode_complete:

                random_value = np.random.random()
                if log_level <= 20:
                    self.FLenv.render()
                action, step_random = self.select_action(state, random_value)
                ep_steps_random += int(step_random)
                logging.info('Action chosen: %d', action)
                logging.debug('Action feasible: %s', not np.isnan(self.R[state, action]))
                state_new, _, episode_complete, _ = self.FLenv.step(action)

                logging.info('New state is %d', state_new)
                reward = self.R[state, action]
                logging.info('Reward: %d', reward)
                self.update_Q(state, action, reward, state_new)
                self.normalise_Q(norm_method)
                logging.info('Q matrix updated: %s', self.Q)
                ep_total_reward += self.Q[state, action]
                state, state_new = state_new, None
                self.update_epsilon(random_value)

                logging.info('*** Completed Step %d of Episode %d ***', step, episode)
                step += 1

            ep_outcome = self.map[self.from_state(state)]
            state = self.FLenv.reset()
            state_new = None

            # Calculate and report metrics for the episode
            ep_steps = step  # N.B steps are numbered from 0 but +=1 in loop accounts for this
            ep_met = episode_metrics()
            logging.info('\nEpisode Complete\n%s\n%s\n%s\n%s', '*' * 30, metric_headers(), ep_met, '*' * 30)
            if write_file:
                outfile.write('%s\n' % ep_met)

            episode += 1

        if write_file:
            if in_memory:
                return outfile
            outfile.close()


class FrozenSarsaLearner(FrozenLearner):

    def __init__(self, episodes, alpha, gamma, td_lambda):
        super(FrozenSarsaLearner,self).__init__(episodes,alpha,gamma)
        self.td_lambda = td_lambda

    def init_E(self):
        self.E = np.zeros((self.numS,self.numA))

    def select_action(self,state,method):
        poss_Q = self.Q[state, :]
        logging.debug('Selecting from Q values %s', poss_Q)
        if method=='random':
            return self.rdm_opt_act(state)
        elif method=='non-random':
            return np.nanargmax(poss_Q)
        else:
            raise ValueError('Unknown method')

    def update_E(self,state,action):
        self.E *= self.gamma * self.td_lambda
        self.E[state,action] = 1

    def update_Q(self, learned_value):
        self.Q += (self.alpha * learned_value * self.E)

    def execute(self, log_level, write_file, file_desc, norm_method='max', select_method='non-random', in_memory=False):

        logging.basicConfig(level=log_level)

        episode = 0
        state = self.FLenv.reset()
        self.init_R(val_goal=100, val_other=0, wall_moves=False)
        logging.info('%s\nRunning SARSA Experiment\n alpha=%3.2f,gamma=%3.2f,lambda=%3.2f \n%s',
                     '*' * 30, self.alpha, self.gamma,self.td_lambda, '*' * 30)
        logging.debug('Reward matrix %s', self.R)
        self.init_Q()
        self.init_E()

        def episode_metrics():
            return '%d,%d,%4.2f,%s' % (episode, ep_steps, ep_total_reward, ep_outcome)

        def metric_headers():
            return 'Episode,Steps,Total_Reward,Outcome'

        # Write the results of each episode to file
        if write_file:
            outfile = self.open_file(in_memory, file_desc, metric_headers())

        # Start SARSA
        while episode < self.episodes:
            episode_complete = False
            step = 0
            ep_total_reward = 0
            action = self.rdm_opt_act(state)
            self.init_E()

            while not episode_complete:

                if log_level <= 20:
                    self.FLenv.render()
                reward = self.R[state, action]
                logging.debug('State %d,action %d before reward',state,action)
                logging.info('Reward: %d', reward)
                state_new, _, episode_complete, _ = self.FLenv.step(action)
                logging.info('New state is %d', state_new)
                action_new = self.select_action(state_new,select_method)
                logging.info('New action chosen: %d', action_new)
                logging.debug('New action feasible: %s', not np.isnan(self.R[state_new, action_new]))
                self.update_E(state,action)
                logging.info('E matrix updated: %s',self.E)
                learned_value = self.R[state,action] + self.gamma * (self.Q[state_new,action_new]-self.Q[state,action])
                logging.debug('Learned value: %4.2f',learned_value)
                self.update_Q(learned_value)
                self.normalise_Q(norm_method)
                logging.info('Q matrix updated: %s', self.Q)

                ep_total_reward += self.Q[state, action]

                state, state_new = state_new, None
                action, action_new = action_new, None

                logging.info('*** Completed Step %d of Episode %d ***', step, episode)
                step += 1

            ep_outcome = self.map[self.from_state(state)]
            state = self.FLenv.reset()
            state_new = None

            # Calculate and report metrics for the episode
            ep_steps = step  # N.B steps are numbered from 0 but +=1 in loop accounts for this
            ep_met = episode_metrics()
            logging.info('\nEpisode Complete\n%s\n%s\n%s\n%s', '*' * 30, metric_headers(), ep_met, '*' * 30)
            if write_file:
                outfile.write('%s\n' % ep_met)

            episode += 1

        if write_file:
            if in_memory:
                return outfile
            outfile.close()
